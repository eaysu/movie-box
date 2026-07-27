"""FastAPI app — yeni mimari.

Akış:
  1. İzlenen filmler scrape edilir  (/films/)   → zevk profili kaynağı
  2. Watchlist scrape edilir         (/watchlist/) → aday havuzu
  3. Her iki liste TMDb ile zenginleştirilir
  4. Watchlist filmleri zevk profiline cosine benzerliğine göre sıralanır
  5. LLM en iyi N filmi seçer ve Türkçe gerekçe yazar

Çalıştırmak için:
  uvicorn app.main:app --reload --port 8001 --log-level warning
"""

import asyncio
import contextlib
import json
import logging
import os
import random as _random
import time
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from .config import get_settings
from .cache import Cache
from .database import upsert_user, SupabaseCache
from .enrich import Enricher, EnrichedFilm
from .llm import rank_candidates
from .recommender import rank_watchlist
from .scraper import ScrapeError, scrape_watchlist, scrape_watched

app = FastAPI(title="Letterboxd AI Recommender", version="0.3.0")
log = logging.getLogger("moviebox")

_allowed_origins = os.environ.get("ALLOWED_ORIGINS", "*").split(",")
app.add_middleware(
    CORSMiddleware,
    allow_origins=_allowed_origins,
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type"],
)

STATIC_DIR = Path(__file__).resolve().parent.parent / "static"
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

# ── Concurrency queue ──────────────────────────────────────────────────────
_sem = asyncio.Semaphore(4)   # max 4 eşzamanlı analiz
_q_lock = asyncio.Lock()
_q_waiting = 0   # sırada bekleyenler
_q_active  = 0   # şu an işlenenler


def _sse(data: dict) -> str:
    return f"data: {json.dumps(data, ensure_ascii=False)}\n\n"


async def _await_with_heartbeat(coro, holder: dict, *, interval: float = 5.0, max_total: float = 75.0):
    """`coro`'yu çalıştırırken her `interval` saniyede bir 'ping' SSE üretir.

    Humanize edilmiş scraping uzun sürebildiğinden (10-40s), bu süre boyunca
    bağlantıyı canlı tutmak için periyodik ping gönderir — aksi halde araya
    giren proxy'ler idle bağlantıyı kesebilir. Sonuç holder['result']'a,
    istisna holder['error']'a yazılır.

    `max_total` saniyeyi aşarsa görev iptal edilir ve holder['error'] bir
    ScrapeError ile doldurulur — Cloudflare'ın olasılıksal engellemesi retry
    bütçesini beklenenden çok aştığında istek sonsuza kadar asılı kalmasın.
    """
    task = asyncio.ensure_future(coro)
    elapsed = 0.0
    while not task.done():
        try:
            await asyncio.wait_for(asyncio.shield(task), timeout=interval)
        except asyncio.TimeoutError:
            elapsed += interval
            if elapsed >= max_total:
                task.cancel()
                with contextlib.suppress(asyncio.CancelledError, Exception):
                    await task
                holder["error"] = ScrapeError(
                    f"Letterboxd {max_total:.0f} saniye içinde yanıt vermedi — "
                    "sunucu IP'si geçici olarak engellenmiş olabilir. Birkaç dakika sonra tekrar dene."
                )
                return
            yield _sse({"type": "ping"})
        except BaseException:
            break  # task hatası aşağıda exception() ile ele alınır
    exc = task.exception()
    if exc is not None:
        holder["error"] = exc
    else:
        holder["result"] = task.result()


def _make_cache(settings):
    sqlite_cache = Cache(settings.cache_db_path)
    if settings.has_supabase:
        from supabase import create_client
        client = create_client(settings.supabase_url, settings.supabase_key)
        return client, sqlite_cache
    return None, sqlite_cache


# ── Kullanıcı profili kalıcı cache'i ─────────────────────────────────────────
# Çekilip zenginleştirilmiş film listeleri kullanıcı başına Supabase'e kaydedilir.
# Sonraki oturumlar scrape + TMDb adımlarını tamamen atlar → ~100s yerine ~5s.
# Supabase yoksa SQLite'a yazılır (lokal kalıcı, Render'da redeploy'da silinir).
TTL_USER_FILMS = 24 * 3600  # 1 gün


def _make_persistent_cache(settings, client):
    """Kullanıcı film profilleri için kalıcı cache (Supabase tercih edilir)."""
    if client is not None:
        return SupabaseCache(client)
    return Cache(settings.cache_db_path)


def _enriched_from_cache(rows: list[dict]) -> list[EnrichedFilm]:
    """Cache JSON'undan EnrichedFilm listesi kur (text_blob hesaplanan alan, atılır)."""
    out: list[EnrichedFilm] = []
    for d in rows:
        d = {k: v for k, v in d.items() if k != "text_blob"}
        out.append(EnrichedFilm(**d))
    return out


async def _load_user_films(
    username: str,
    list_type: str,
    *,
    settings,
    enricher,
    pcache,
    scrape_kwargs: dict,
    force: bool = False,
):
    """Bir kullanıcının bir listesi için zenginleştirilmiş filmleri döndür.

    Sıra: kalıcı cache (Supabase) → yoksa scrape + TMDb enrich → cache'e yaz.
    Sadece TEMIZ biten (complete=True) scrape'ler cache'lenir; bloklu/eksik
    taramalar 24 saat boyunca kötü veri servis etmesin diye yazılmaz.

    force=True → cache okumasını atlar, taze çekip üzerine yazar (cache warmer).
    list_type: 'watched' | 'watchlist'.
    Döner: (list[EnrichedFilm], from_cache: bool).
    """
    ns = f"films_{list_type}"
    if pcache is not None and not force:
        cached = pcache.get(ns, username, ttl=TTL_USER_FILMS)
        if cached:
            log.warning("cache HIT  %s/%s (%d films)", list_type, username, len(cached))
            return _enriched_from_cache(cached), True

    scrape_fn = scrape_watched if list_type == "watched" else scrape_watchlist
    scraped, complete = await scrape_fn(username, **scrape_kwargs)
    if not scraped:
        return [], False

    if enricher is not None:
        films = await enricher.enrich(scraped)
    else:
        films = [
            EnrichedFilm(title=f.title, year=f.year, slug=f.slug, poster_url=f.poster_url)
            for f in scraped
        ]

    # Yalnızca temiz biten taramaları cache'le (eksik profil 24s yapışmasın).
    if pcache is not None and films and complete:
        pcache.set(ns, username, [f.to_dict() for f in films])
        log.warning("cache SET  %s/%s (%d films)", list_type, username, len(films))
    elif not complete:
        log.warning("cache SKIP %s/%s — scrape incomplete (blocked)", list_type, username)

    return films, False


class RecommendRequest(BaseModel):
    username: str


class RandomRequest(BaseModel):
    username: str


class BlendRequest(BaseModel):
    username1: str
    username2: str


@app.get("/")
def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


@app.api_route("/api/health", methods=["GET", "HEAD"])
def health() -> dict:
    settings = get_settings()
    return {
        "status": "ok",
        "tmdb_enabled": settings.has_tmdb,
        "llm_enabled": settings.has_openai,
        "supabase_enabled": settings.has_supabase,
    }


@app.post("/api/recommend")
async def recommend(req: RecommendRequest):
    """SSE stream: queued? → scraping → enriching → ranking → llm → result."""
    global _q_waiting, _q_active

    async def generate():
        global _q_waiting, _q_active
        t0 = time.perf_counter()
        settings = get_settings()

        # Sıraya gir
        async with _q_lock:
            _q_waiting += 1
            ahead = _q_active + _q_waiting - 1

        if ahead > 0:
            yield _sse({"type": "queued", "ahead": ahead})

        async with _sem:
            async with _q_lock:
                _q_waiting -= 1
                _q_active  += 1

            try:
                # Cache + enricher hazırlığı
                supabase_client, cache = _make_cache(settings)
                pcache = _make_persistent_cache(settings, supabase_client)
                if supabase_client is not None:
                    upsert_user(supabase_client, req.username)
                enricher = Enricher(settings.tmdb_api_key, cache) if settings.has_tmdb else None

                watched_kwargs = dict(
                    delay=settings.scrape_delay,
                    max_pages=settings.watched_max_pages,
                    film_limit=settings.watched_film_limit,
                    max_retries=settings.scrape_max_retries,
                    scraperapi_key=settings.scraperapi_key,
                    scraperapi_max_pages=settings.scraperapi_max_pages,
                )
                watchlist_kwargs = dict(
                    delay=settings.scrape_delay,
                    max_pages=settings.scrape_max_pages,
                    film_limit=settings.watchlist_film_limit,
                    max_retries=settings.scrape_max_retries,
                    scraperapi_key=settings.scraperapi_key,
                    scraperapi_max_pages=settings.scraperapi_max_pages,
                )

                # 1+2. Cache'ten oku ya da scrape + TMDb enrich (heartbeat'li)
                yield _sse({"type": "step", "step": "scraping"})
                t1 = time.perf_counter()
                hs: dict = {}
                async for ping in _await_with_heartbeat(
                    asyncio.gather(
                        _load_user_films(req.username, "watched", settings=settings,
                                         enricher=enricher, pcache=pcache, scrape_kwargs=watched_kwargs),
                        _load_user_films(req.username, "watchlist", settings=settings,
                                         enricher=enricher, pcache=pcache, scrape_kwargs=watchlist_kwargs),
                    ),
                    hs,
                ):
                    yield ping
                if "error" in hs:
                    exc = hs["error"]
                    if isinstance(exc, ScrapeError):
                        yield _sse({"type": "error", "detail": str(exc)})
                        return
                    raise exc
                (watched_films, w_cached), (watchlist_films, wl_cached) = hs["result"]
                yield _sse({"type": "step", "step": "enriching"})
                log.warning("⏱ load films      %.2fs  (watched=%d[cache=%s], watchlist=%d[cache=%s])",
                            time.perf_counter() - t1, len(watched_films), w_cached,
                            len(watchlist_films), wl_cached)

                if not watchlist_films:
                    yield _sse({"type": "error", "detail": "Watchlist boş veya gizli."})
                    return

                # 3. TF-IDF ranking
                yield _sse({"type": "step", "step": "ranking"})
                t3 = time.perf_counter()
                candidate_count = settings.num_recommendations * 2
                candidates = rank_watchlist(watched_films, watchlist_films, n=candidate_count)
                log.warning("⏱ tfidf rank      %.2fs  (candidates=%d)", time.perf_counter() - t3, len(candidates))

                # 4. LLM
                yield _sse({"type": "step", "step": "llm"})
                t4 = time.perf_counter()
                result = await rank_candidates(settings, watched_films, candidates)
                log.warning("⏱ llm rerank      %.2fs  (llm_used=%s)", time.perf_counter() - t4, result.get("llm_used"))
                log.warning("⏱ TOTAL           %.2fs", time.perf_counter() - t0)

                yield _sse({
                    "type": "result",
                    "username": req.username,
                    "watched_count": len(watched_films),
                    "watchlist_count": len(watchlist_films),
                    "taste_summary": result["taste_summary"],
                    "recommendations": result["recommendations"],
                    "meta": {
                        "tmdb_enabled": settings.has_tmdb,
                        "llm_used": result.get("llm_used", False),
                    },
                })

            except Exception as exc:
                log.warning("pipeline error: %s", exc)
                yield _sse({"type": "error", "detail": "Beklenmeyen bir hata oluştu."})

            finally:
                async with _q_lock:
                    _q_active -= 1

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.post("/api/random")
async def random_pick(req: RandomRequest):
    """SSE stream: watchlist'ten 3 rastgele film seç ve zenginleştir."""

    async def generate():
        settings = get_settings()
        supabase_client, cache = _make_cache(settings)
        pcache = _make_persistent_cache(settings, supabase_client)

        # 0. Kalıcı cache'te zenginleştirilmiş watchlist varsa → scrape'siz seç
        cached = pcache.get("films_watchlist", req.username, ttl=TTL_USER_FILMS) if pcache else None
        if cached:
            enriched = _enriched_from_cache(cached)
            with_poster = [f for f in enriched if f.poster_url]
            pool = with_poster if len(with_poster) >= 3 else enriched
            if not pool:
                yield _sse({"type": "error", "detail": "Watchlist boş veya gizli."})
                return
            chosen = _random.sample(pool, min(3, len(pool)))
            log.warning("cache HIT  watchlist/%s (random pick)", req.username)
            yield _sse({
                "type": "result",
                "username": req.username,
                "watchlist_count": len(enriched),
                "films": [f.to_dict() for f in chosen],
            })
            return

        # 1. Cache yok → scrape (heartbeat'li). Ucuz yol: sadece seçilen 3 film enrich.
        yield _sse({"type": "step", "step": "scraping"})
        hr: dict = {}
        async for ping in _await_with_heartbeat(
            scrape_watchlist(
                req.username,
                delay=settings.scrape_delay,
                max_pages=settings.scrape_max_pages,
                film_limit=settings.watchlist_film_limit,
                max_retries=settings.scrape_max_retries,
                scraperapi_key=settings.scraperapi_key,
                scraperapi_max_pages=settings.scraperapi_max_pages,
            ),
            hr,
        ):
            yield ping
        if "error" in hr:
            exc = hr["error"]
            if isinstance(exc, ScrapeError):
                yield _sse({"type": "error", "detail": str(exc)})
                return
            raise exc
        scraped_watchlist, _complete = hr["result"]

        if not scraped_watchlist:
            yield _sse({"type": "error", "detail": "Watchlist boş veya gizli."})
            return

        # Posteri olan filmler varsa onlardan seç — postersize film göstermemek için.
        with_poster = [f for f in scraped_watchlist if f.poster_url]
        pool = with_poster if len(with_poster) >= 3 else scraped_watchlist
        count = min(3, len(pool))
        chosen = _random.sample(pool, count)

        yield _sse({"type": "step", "step": "enriching"})
        if settings.has_tmdb:
            enricher = Enricher(settings.tmdb_api_key, cache)
            films = await enricher.enrich(chosen)
        else:
            films = [
                EnrichedFilm(title=f.title, year=f.year, slug=f.slug, poster_url=f.poster_url)
                for f in chosen
            ]

        yield _sse({
            "type": "result",
            "username": req.username,
            "watchlist_count": len(scraped_watchlist),
            "films": [f.to_dict() for f in films],
        })

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


def _calculate_blend(watched1: list, watched2: list, top_n: int = 20) -> dict:
    """Blend skoru, ortak filmler ve ortak yönetmen hesapla."""
    from collections import Counter
    import numpy as np
    from sklearn.metrics.pairwise import cosine_similarity

    def _cos(c1: Counter, c2: Counter) -> float:
        """İki Counter arasında cosine similarity."""
        keys = sorted(set(c1) | set(c2))
        if not keys:
            return 0.0
        v1 = np.array([c1.get(k, 0) for k in keys], dtype=float)
        v2 = np.array([c2.get(k, 0) for k in keys], dtype=float)
        if not v1.any() or not v2.any():
            return 0.0
        return float(cosine_similarity(v1.reshape(1, -1), v2.reshape(1, -1))[0][0])

    def _rating_weight(f) -> float:
        """Puanlı filmler daha fazla ağırlık taşır; puan yoksa nötr (3.0) kabul et."""
        r = f.user_rating
        return (r / 3.0) if r else 1.0

    # ── Ortak filmler ──────────────────────────────────────────────────────
    # 1. Slug eşleşmesi (birincil)
    slugs2 = {f.slug for f in watched2 if f.slug}
    common_slugs = [f for f in watched1 if f.slug and f.slug in slugs2]

    # 2. Başlık+yıl eşleşmesi (ikincil — slug yoksa veya eksikse)
    seen_slugs = {f.slug for f in common_slugs}
    keys2 = {(f.title.lower().strip(), f.year) for f in watched2}
    common_title = [
        f for f in watched1
        if f.slug not in seen_slugs
        and (f.title.lower().strip(), f.year) in keys2
    ]
    common = common_slugs + common_title
    common_count = len(common)
    # Posteri olan filmler öne gelsin; eşitlikte vote_average'a bak.
    common.sort(key=lambda f: (f.poster_url is not None, f.vote_average), reverse=True)
    top_common = common[:top_n]

    # ── Uyum skoru ─────────────────────────────────────────────────────────
    # Sinyal 1-4: Rating-ağırlıklı özellik vektörleri
    # 5 yıldız verilen film, 1 yıldızlı filmden ~5x daha fazla zevk profilini şekillendirir.
    def _weighted_counter(films, key_fn) -> Counter:
        c: Counter = Counter()
        for f in films:
            w = _rating_weight(f)
            for k in key_fn(f):
                c[k] += w
        return c

    genre_sim = _cos(
        _weighted_counter(watched1, lambda f: f.genres or []),
        _weighted_counter(watched2, lambda f: f.genres or []),
    )
    kw_sim = _cos(
        _weighted_counter(watched1, lambda f: f.keywords or []),
        _weighted_counter(watched2, lambda f: f.keywords or []),
    )
    dir_sim = _cos(
        _weighted_counter(watched1, lambda f: [f.director] if f.director else []),
        _weighted_counter(watched2, lambda f: [f.director] if f.director else []),
    )
    era_sim = _cos(
        _weighted_counter(watched1, lambda f: [(f.year // 10) * 10] if f.year else []),
        _weighted_counter(watched2, lambda f: [(f.year // 10) * 10] if f.year else []),
    )

    # Sinyal 5: Ortak filmlerde rating korelasyonu (Pearson)
    # Her iki kullanıcının da puan verdiği ortak filmlerde, aynı filmleri
    # benzer şekilde değerlendiriyorlarsa güçlü uyum sinyali.
    rating_corr = 0.0
    w2_by_slug = {f.slug: f for f in watched2 if f.slug}
    w2_by_key  = {(f.title.lower().strip(), f.year): f for f in watched2}
    pairs: list[tuple[float, float]] = []
    for f1 in watched1:
        if f1.user_rating is None:
            continue
        f2 = w2_by_slug.get(f1.slug) if f1.slug else None
        if f2 is None:
            f2 = w2_by_key.get((f1.title.lower().strip(), f1.year))
        if f2 and f2.user_rating is not None:
            pairs.append((f1.user_rating, f2.user_rating))

    if len(pairs) >= 3:
        r1 = np.array([p[0] for p in pairs])
        r2 = np.array([p[1] for p in pairs])
        # Pearson correlation: NaN güvenliği için std kontrolü
        if r1.std() > 0 and r2.std() > 0:
            rating_corr = float(np.corrcoef(r1, r2)[0, 1])
            rating_corr = max(rating_corr, 0.0)  # negatif korelasyon → 0 (ceza vermiyoruz)

    # Genre ve era sinyalleri çok non-discriminating (herkes Drama/Comedy, herkes 2010s izliyor).
    # Keyword ve director gerçek zevk ayrımını yapar — ağırlıkları yükselt.
    if pairs:
        raw = (genre_sim * 0.04 + kw_sim * 0.37 + dir_sim * 0.37
               + era_sim * 0.02 + rating_corr * 0.20)
    else:
        raw = genre_sim * 0.05 + kw_sim * 0.47 + dir_sim * 0.47 + era_sim * 0.01

    # Skor haritalama: yeterli veri varsa [70, 97], az verili çiftler ham skor alır.
    # Letterboxd kullanıcıları zaten film tutkunları — "en farklı" çift bile 70'e layık.
    # 50 film altı taranan kullanıcılar için güvenilir profil çıkmaz.
    min_watched = min(len(watched1), len(watched2))
    if min_watched >= 50:
        # raw ≈ 0.0 (tamamen farklı) → 70,  raw ≈ 0.65+ (çok benzer) → 97
        MAX_RAW = 0.65
        normalized = max(0.0, min(raw / MAX_RAW, 1.0))
        score = round(70 + normalized * 27)
    else:
        # Veri yetersiz: ham skor, 69 tavanı
        score = max(3, min(69, round(raw * 1.5 * 100)))

    # ── Ortak en sevilen yönetmen ───────────────────────────────────────────
    directors1 = Counter(f.director for f in watched1 if f.director)
    directors2 = Counter(f.director for f in watched2 if f.director)
    common_dirs = set(directors1) & set(directors2)

    if common_dirs:
        # min(d1, d2): her iki kullanıcının da gerçekten sevdiği yönetmeni öne çıkar.
        # Toplam (d1+d2) yerine min kullanmak tek taraflı baskınlığı engeller.
        # Eşitlikte toplam tiebreaker olarak kullanılır.
        scored = {d: (min(directors1[d], directors2[d]), directors1[d] + directors2[d])
                  for d in common_dirs}
        top_dir = max(scored, key=scored.get)
    else:
        top_dir = None

    return {
        "score": score,
        "common_count": common_count,
        "top_director": top_dir,
        "top_director_count1": directors1.get(top_dir, 0) if top_dir else 0,
        "top_director_count2": directors2.get(top_dir, 0) if top_dir else 0,
        "films": top_common,
    }


@app.post("/api/blend")
async def blend(req: BlendRequest):
    """SSE stream: iki kullanıcının film zevkini harmanlayıp uyum skoru hesapla."""
    log.warning("blend request: %s / %s", req.username1, req.username2)

    async def generate():
        t0 = time.perf_counter()
        settings = get_settings()
        try:
            supabase_client, cache = _make_cache(settings)
            pcache = _make_persistent_cache(settings, supabase_client)
            if supabase_client is not None:
                upsert_user(supabase_client, req.username1)
                upsert_user(supabase_client, req.username2)
            enricher = Enricher(settings.tmdb_api_key, cache) if settings.has_tmdb else None

            watched_kwargs = dict(
                delay=settings.scrape_delay, max_pages=settings.watched_max_pages,
                film_limit=settings.watched_film_limit, max_retries=settings.scrape_max_retries,
                scraperapi_key=settings.scraperapi_key, scraperapi_max_pages=settings.scraperapi_max_pages,
            )
            watchlist_kwargs = dict(
                delay=settings.scrape_delay, max_pages=settings.scrape_max_pages,
                film_limit=settings.watchlist_film_limit, max_retries=settings.scrape_max_retries,
                scraperapi_key=settings.scraperapi_key, scraperapi_max_pages=settings.scraperapi_max_pages,
            )

            def _load(username, list_type, kwargs):
                return _load_user_films(username, list_type, settings=settings,
                                        enricher=enricher, pcache=pcache, scrape_kwargs=kwargs)

            async def _safe_load(username, list_type, kwargs):
                try:
                    return await _load(username, list_type, kwargs)
                except ScrapeError:
                    return [], False

            yield _sse({"type": "step", "step": "scraping"})
            t1 = time.perf_counter()

            # ── Faz 1: izlenen filmler (cache→scrape+enrich, paralel, heartbeat'li) ──
            h1: dict = {}
            async for ping in _await_with_heartbeat(
                asyncio.gather(
                    _load(req.username1, "watched", watched_kwargs),
                    _load(req.username2, "watched", watched_kwargs),
                ), h1,
            ):
                yield ping
            if "error" in h1:
                exc = h1["error"]
                if isinstance(exc, ScrapeError):
                    log.warning("blend scrape error (watched): %s", exc)
                    yield _sse({"type": "error", "detail": str(exc)})
                    return
                raise exc
            (w1_enriched, _c1), (w2_enriched, _c2) = h1["result"]

            if not w1_enriched:
                yield _sse({"type": "error", "detail": f"@{req.username1} profili bulunamadı veya gizli."})
                return
            if not w2_enriched:
                yield _sse({"type": "error", "detail": f"@{req.username2} profili bulunamadı veya gizli."})
                return

            yield _sse({"type": "step", "step": "enriching"})

            # ── Faz 2: watchlist (opsiyonel, cache→scrape+enrich, heartbeat'li) ──────
            h2: dict = {}
            async for ping in _await_with_heartbeat(
                asyncio.gather(
                    _safe_load(req.username1, "watchlist", watchlist_kwargs),
                    _safe_load(req.username2, "watchlist", watchlist_kwargs),
                ), h2,
            ):
                yield ping
            if "error" in h2:
                raise h2["error"]
            (wl1e, _w1), (wl2e, _w2) = h2["result"]

            log.warning("blend load %.2fs  w1=%d w2=%d wl1=%d wl2=%d",
                        time.perf_counter() - t1, len(w1_enriched), len(w2_enriched), len(wl1e), len(wl2e))

            # ── Ortak watchlist filmleri (zenginleştirilmiş listelerden) ────────────
            wl_slugs2 = {f.slug for f in wl2e if f.slug}
            common_wl = [f for f in wl1e if f.slug and f.slug in wl_slugs2]
            seen_wl = {f.slug for f in common_wl}
            wl_keys2 = {(f.title.lower().strip(), f.year) for f in wl2e}
            common_wl += [
                f for f in wl1e
                if f.slug not in seen_wl and (f.title.lower().strip(), f.year) in wl_keys2
            ]
            common_wl.sort(key=lambda f: (f.poster_url is not None, f.vote_average), reverse=True)
            common_wl_films = common_wl[:3]

            # ── Ranking ───────────────────────────────────────────────────────────
            yield _sse({"type": "step", "step": "ranking"})
            result = _calculate_blend(w1_enriched, w2_enriched, top_n=20)

            log.warning("blend TOTAL %.2fs  score=%d common=%d",
                        time.perf_counter() - t0, result["score"], result["common_count"])

            yield _sse({
                "type": "result",
                "username1": req.username1,
                "username2": req.username2,
                "score": result["score"],
                "watched_count1": len(w1_enriched),
                "watched_count2": len(w2_enriched),
                "common_count": result["common_count"],
                "top_director": result["top_director"],
                "top_director_count1": result["top_director_count1"],
                "top_director_count2": result["top_director_count2"],
                "films": [f.to_dict() for f in result["films"]],
                "common_watchlist_films": [f.to_dict() for f in common_wl_films],
                "watchlist_public": len(wl1e) > 0 and len(wl2e) > 0,
            })

        except BaseException as exc:
            # BaseException yakalar: Exception + CancelledError + diğerleri
            if not isinstance(exc, (SystemExit, KeyboardInterrupt)):
                log.warning("blend EXCEPTION %s: %s", type(exc).__name__, exc)
                yield _sse({"type": "error", "detail": f"Sunucu hatası: {type(exc).__name__} — {exc}"})

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
