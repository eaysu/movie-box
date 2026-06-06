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
from .database import upsert_user
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


def _make_cache(settings):
    sqlite_cache = Cache(settings.cache_db_path)
    if settings.has_supabase:
        from supabase import create_client
        client = create_client(settings.supabase_url, settings.supabase_key)
        return client, sqlite_cache
    return None, sqlite_cache


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
                # 1. Scraping
                yield _sse({"type": "step", "step": "scraping"})
                t1 = time.perf_counter()
                try:
                    scraped_watched, scraped_watchlist = await asyncio.gather(
                        scrape_watched(
                            req.username,
                            delay=settings.scrape_delay,
                            max_pages=settings.watched_max_pages,
                            film_limit=settings.watched_film_limit,
                        ),
                        scrape_watchlist(
                            req.username,
                            delay=settings.scrape_delay,
                            max_pages=settings.scrape_max_pages,
                            film_limit=settings.watchlist_film_limit,
                        ),
                    )
                except ScrapeError as exc:
                    yield _sse({"type": "error", "detail": str(exc)})
                    return
                log.warning("⏱ scraping       %.2fs  (watched=%d, watchlist=%d)",
                            time.perf_counter() - t1, len(scraped_watched), len(scraped_watchlist))

                if not scraped_watchlist:
                    yield _sse({"type": "error", "detail": "Watchlist boş veya gizli."})
                    return

                # 2. TMDb enrichment
                yield _sse({"type": "step", "step": "enriching"})
                t2 = time.perf_counter()
                supabase_client, cache = _make_cache(settings)
                if supabase_client is not None:
                    upsert_user(supabase_client, req.username)

                if settings.has_tmdb:
                    enricher = Enricher(settings.tmdb_api_key, cache)
                    watched_films, watchlist_films = await asyncio.gather(
                        enricher.enrich(scraped_watched),
                        enricher.enrich(scraped_watchlist),
                    )
                else:
                    watched_films = [
                        EnrichedFilm(title=f.title, year=f.year, slug=f.slug)
                        for f in scraped_watched
                    ]
                    watchlist_films = [
                        EnrichedFilm(title=f.title, year=f.year, slug=f.slug, poster_url=f.poster_url)
                        for f in scraped_watchlist
                    ]
                cache_hits = getattr(enricher, "_cache_hits", "?") if settings.has_tmdb else 0
                log.warning("⏱ tmdb enrich     %.2fs  (sqlite_hits=%s)", time.perf_counter() - t2, cache_hits)

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

        yield _sse({"type": "step", "step": "scraping"})
        try:
            scraped_watchlist = await scrape_watchlist(
                req.username,
                delay=settings.scrape_delay,
                max_pages=settings.scrape_max_pages,
                film_limit=settings.watchlist_film_limit,
            )
        except ScrapeError as exc:
            yield _sse({"type": "error", "detail": str(exc)})
            return

        if not scraped_watchlist:
            yield _sse({"type": "error", "detail": "Watchlist boş veya gizli."})
            return

        # Posteri olan filmler varsa onlardan seç — postersize film göstermemek için.
        # Letterboxd watchlist HTML'i neredeyse her zaman poster thumbnail içerir,
        # bu yüzden filtreleme sonrası yeterli havuz kalır.
        with_poster = [f for f in scraped_watchlist if f.poster_url]
        pool = with_poster if len(with_poster) >= 3 else scraped_watchlist
        count = min(3, len(pool))
        chosen = _random.sample(pool, count)

        yield _sse({"type": "step", "step": "enriching"})
        _, cache = _make_cache(settings)
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

    # Ağırlıklar: keyword ve director en ayrıştırıcı sinyaller.
    # Rating korelasyonu varsa %20 pay alır, yoksa diğer sinyallere dağıtılır.
    if pairs:
        raw = (genre_sim * 0.12 + kw_sim * 0.28 + dir_sim * 0.28
               + era_sim * 0.12 + rating_corr * 0.20)
    else:
        raw = genre_sim * 0.15 + kw_sim * 0.35 + dir_sim * 0.35 + era_sim * 0.15

    # Tipik raw: farklı kullanıcılar 0.15-0.25, benzer 0.35-0.60 → ×1.6
    score = max(min(round(raw * 1.6 * 100), 98), 2)

    # ── Ortak en sevilen yönetmen ───────────────────────────────────────────
    directors1 = Counter(f.director for f in watched1 if f.director)
    directors2 = Counter(f.director for f in watched2 if f.director)
    common_dirs = set(directors1) & set(directors2)

    if common_dirs:
        scored = {d: directors1[d] + directors2[d] for d in common_dirs}
        top_dir = max(scored, key=scored.get)
    elif directors1 or directors2:
        top_dir = (directors1 + directors2).most_common(1)[0][0]
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

    async def generate():
        settings = get_settings()

        yield _sse({"type": "step", "step": "scraping"})
        try:
            # Blend için daha fazla film çek — ortak film bulma şansı artsın.
            # max_pages=5: 403 gelirse sessizce durur (scraper bunu handle ediyor).
            watched1, watched2 = await asyncio.gather(
                scrape_watched(req.username1, delay=settings.scrape_delay,
                               max_pages=5, film_limit=400),
                scrape_watched(req.username2, delay=settings.scrape_delay,
                               max_pages=5, film_limit=400),
            )
        except ScrapeError as exc:
            yield _sse({"type": "error", "detail": str(exc)})
            return

        if not watched1:
            yield _sse({"type": "error", "detail": f"@{req.username1} profili bulunamadı veya gizli."})
            return
        if not watched2:
            yield _sse({"type": "error", "detail": f"@{req.username2} profili bulunamadı veya gizli."})
            return

        yield _sse({"type": "step", "step": "enriching"})
        _, cache = _make_cache(settings)
        if settings.has_tmdb:
            enricher = Enricher(settings.tmdb_api_key, cache)
            w1_enriched, w2_enriched = await asyncio.gather(
                enricher.enrich(watched1),
                enricher.enrich(watched2),
            )
        else:
            w1_enriched = [EnrichedFilm(title=f.title, year=f.year, slug=f.slug) for f in watched1]
            w2_enriched = [EnrichedFilm(title=f.title, year=f.year, slug=f.slug) for f in watched2]

        yield _sse({"type": "step", "step": "ranking"})
        result = _calculate_blend(w1_enriched, w2_enriched, top_n=20)

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
        })

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
