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
import hashlib
import json
import logging
import os
import random as _random
import re
import time
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, field_validator

from .config import get_settings
from .cache import Cache, LayeredCache
from .database import delete_user, upsert_user, SupabaseCache
from .enrich import Enricher, EnrichedFilm, close_tmdb_client
from .llm import rank_candidates
from .recommender import rank_watchlist
from .rate_limit import SlidingWindowRateLimiter
from .scraper import ScrapeError, scrape_diary, scrape_watchlist, scrape_watched


@contextlib.asynccontextmanager
async def _lifespan(_app):
    yield
    await close_tmdb_client()


app = FastAPI(title="Letterboxd AI Recommender", version="0.3.0", lifespan=_lifespan)
log = logging.getLogger("moviebox")

_allowed_origins = os.environ.get("ALLOWED_ORIGINS", "*").split(",")
app.add_middleware(
    CORSMiddleware,
    allow_origins=_allowed_origins,
    allow_methods=["GET", "POST", "DELETE"],
    allow_headers=["Content-Type"],
)

STATIC_DIR = Path(__file__).resolve().parent.parent / "static"
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

# ── Concurrency queue ──────────────────────────────────────────────────────
_sem = asyncio.Semaphore(4)   # max 4 eşzamanlı analiz
_q_lock = asyncio.Lock()
_q_waiting = 0   # sırada bekleyenler
_q_active  = 0   # şu an işlenenler

_heavy_rate_limiter = SlidingWindowRateLimiter(
    limit=5,
    window_seconds=10 * 60,
    burst=2,
    burst_seconds=15,
)
_delete_rate_limiter = SlidingWindowRateLimiter(
    limit=3,
    window_seconds=60 * 60,
    burst=1,
    burst_seconds=15,
)


def _client_ip(request: Request) -> str:
    """Resolve the client IP behind Render/Cloudflare without trusting left XFF."""
    cf_ip = request.headers.get("cf-connecting-ip", "").strip()
    if cf_ip:
        return cf_ip
    forwarded = request.headers.get("x-forwarded-for", "")
    if forwarded:
        # Cloudflare appends the actual visitor address; a caller can spoof the
        # left side of the chain, so use the rightmost non-empty address.
        addresses = [part.strip() for part in forwarded.split(",") if part.strip()]
        if addresses:
            return addresses[-1]
    return request.client.host if request.client else "unknown"


async def _enforce_heavy_rate_limit(request: Request) -> None:
    allowed, retry_after = await _heavy_rate_limiter.check(_client_ip(request))
    if not allowed:
        raise HTTPException(
            status_code=429,
            detail="Çok fazla analiz isteği gönderildi. Lütfen biraz sonra tekrar dene.",
            headers={"Retry-After": str(retry_after)},
        )


async def _enforce_delete_rate_limit(request: Request) -> None:
    allowed, retry_after = await _delete_rate_limiter.check(_client_ip(request))
    if not allowed:
        raise HTTPException(
            status_code=429,
            detail="Çok fazla veri silme isteği gönderildi. Lütfen daha sonra tekrar dene.",
            headers={"Retry-After": str(retry_after)},
        )


def _sse(data: dict) -> str:
    return f"data: {json.dumps(data, ensure_ascii=False)}\n\n"


def _scrape_error_event(exc: ScrapeError) -> str:
    return _sse({"type": "error", "code": exc.code, "detail": str(exc)})


async def _await_with_heartbeat(coro, holder: dict, *, interval: float = 5.0, max_total: float = 120.0):
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


async def _capacity_stream(stream):
    """Run an SSE iterator under the shared endpoint concurrency budget."""
    global _q_waiting, _q_active

    acquired = False
    waiting = True
    active = False
    async with _q_lock:
        _q_waiting += 1
        ahead = _q_active + _q_waiting - 1

    try:
        if ahead > 0:
            yield _sse({"type": "queued", "ahead": ahead})

        await _sem.acquire()
        acquired = True

        async with _q_lock:
            _q_waiting -= 1
            waiting = False
            _q_active += 1
            active = True

        async for event in stream:
            yield event
    finally:
        if acquired:
            _sem.release()
        if waiting or active:
            async with _q_lock:
                if waiting:
                    _q_waiting -= 1
                if active:
                    _q_active -= 1
        with contextlib.suppress(asyncio.CancelledError, Exception):
            await stream.aclose()


def _make_cache(settings):
    sqlite_cache = Cache(settings.cache_db_path)
    if settings.has_supabase:
        from supabase import create_client
        client = create_client(settings.supabase_url, settings.supabase_key)
        return client, LayeredCache(sqlite_cache, SupabaseCache(client))
    return None, sqlite_cache


# ── Kullanıcı profili kalıcı cache'i ─────────────────────────────────────────
# Çekilip zenginleştirilmiş film listeleri kullanıcı başına Supabase'e kaydedilir.
# Sonraki oturumlar scrape + TMDb adımlarını tamamen atlar → ~100s yerine ~5s.
# Supabase yoksa SQLite'a yazılır (lokal kalıcı, Render'da redeploy'da silinir).
TTL_USER_FILMS = 24 * 3600  # 1 gün
TTL_FULL_SCRAPE = 7 * 24 * 3600  # derindeki silme/değişiklikler için haftalık tam crawl
FINGERPRINT_FILM_LIMIT = 28
TTL_RECOMMENDATION = 30 * 24 * 3600
RECOMMENDER_VERSION = "v2-rating-mmr"


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
        if "details_loaded" not in d:
            d["details_loaded"] = bool(d.get("director") or d.get("keywords"))
        out.append(EnrichedFilm(**d))
    return out


def _detail_sample(films: list[EnrichedFilm], limit: int) -> list[EnrichedFilm]:
    """Prefer explicitly high-rated films, then preserve recent profile order."""
    rated = sorted(
        (film for film in films if film.user_rating is not None),
        key=lambda film: film.user_rating or 0.0,
        reverse=True,
    )
    rated_ids = {id(film) for film in rated}
    return (rated + [film for film in films if id(film) not in rated_ids])[:limit]


def _recommendation_namespace(username: str) -> str:
    """Keep recommendation rows deletable without weakening content-addressed keys."""
    return f"recommendations:{username}"


def _delete_cached_user_data(cache, username: str) -> bool:
    """Delete every username-addressable cache row from one backend."""
    operations = [
        cache.delete("films_watched", username),
        cache.delete("films_watchlist", username),
        cache.delete("films_full_refresh", f"watched:{username}"),
        cache.delete("films_full_refresh", f"watchlist:{username}"),
        cache.clear(_recommendation_namespace(username)),
        # Pre-v3 recommendation rows were anonymous hashes and cannot be mapped
        # to a username. The obsolete namespace is no longer read.
        cache.clear("recommendations"),
    ]
    return all(result is not False for result in operations)


def _recommendation_cache_key(
    username: str,
    watched: list[EnrichedFilm],
    watchlist: list[EnrichedFilm],
    *,
    model: str,
    count: int,
) -> str:
    """Content-address a recommendation so profile changes invalidate it."""
    payload = {
        "version": RECOMMENDER_VERSION,
        "username": username,
        "model": model,
        "count": count,
        "watched": [(film.slug, film.user_rating) for film in watched],
        "watchlist": [film.slug for film in watchlist],
    }
    digest = hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    return digest


_film_load_flights: dict[tuple[str, str], asyncio.Task] = {}
_film_load_lock = asyncio.Lock()


async def _scrape_enrich_and_cache(
    username: str,
    list_type: str,
    *,
    enricher,
    pcache,
    scrape_kwargs: dict,
    cached_rows: list[dict] | None = None,
    allow_head_check: bool = False,
):
    """Cache miss sonrası pahalı scrape + enrichment işini bir kez çalıştır."""
    ns = f"films_{list_type}"

    if cached_rows and allow_head_check:
        expected = [row.get("slug", "") for row in cached_rows[:FINGERPRINT_FILM_LIMIT]]
        if expected and all(expected):
            try:
                if list_type == "watched":
                    head, _ = await scrape_diary(
                        username,
                        max_pages=1,
                        film_limit=FINGERPRINT_FILM_LIMIT,
                        max_retries=scrape_kwargs.get("max_retries", 3),
                    )
                else:
                    head, _ = await scrape_watchlist(
                        username,
                        delay=0,
                        max_pages=1,
                        film_limit=FINGERPRINT_FILM_LIMIT,
                        max_retries=scrape_kwargs.get("max_retries", 3),
                    )
                actual = [film.slug for film in head]
                if actual == expected[:len(actual)] and len(actual) == len(expected):
                    await asyncio.to_thread(pcache.touch, ns, username)
                    log.warning(
                        "fingerprint HIT %s/%s (%d head slugs); full crawl skipped",
                        list_type,
                        username,
                        len(actual),
                    )
                    return _enriched_from_cache(cached_rows), True
            except ScrapeError as exc:
                log.warning("fingerprint check failed %s/%s: %s", list_type, username, exc)

    scrape_fn = scrape_watched if list_type == "watched" else scrape_watchlist
    scraped, complete = await scrape_fn(username, **scrape_kwargs)
    if not scraped:
        return [], False

    if enricher is not None:
        # Profile cache stores cheap search metadata. Director/keywords are fetched
        # later only for the small subset that affects ranking or Blend.
        films = await enricher.enrich(scraped, include_details=False)
    else:
        films = [
            EnrichedFilm(title=f.title, year=f.year, slug=f.slug, poster_url=f.poster_url)
            for f in scraped
        ]

    # Yalnızca temiz biten taramaları cache'le (eksik profil 24s yapışmasın).
    if pcache is not None and films and complete:
        await asyncio.to_thread(pcache.set, ns, username, [f.to_dict() for f in films])
        await asyncio.to_thread(
            pcache.set,
            "films_full_refresh",
            f"{list_type}:{username}",
            {"complete": True},
        )
        log.warning("cache SET  %s/%s (%d films)", list_type, username, len(films))
    elif not complete:
        log.warning("cache SKIP %s/%s — scrape incomplete (blocked)", list_type, username)

    return films, False


async def _get_or_create_film_flight(
    username: str,
    list_type: str,
    *,
    enricher,
    pcache,
    scrape_kwargs: dict,
    cached_rows: list[dict] | None = None,
    allow_head_check: bool = False,
) -> tuple[asyncio.Task, bool]:
    """Return the shared refresh task and whether this caller joined it."""
    flight_key = (username, list_type)
    async with _film_load_lock:
        task = _film_load_flights.get(flight_key)
        if task is not None:
            return task, True

        task = asyncio.create_task(
            _scrape_enrich_and_cache(
                username,
                list_type,
                enricher=enricher,
                pcache=pcache,
                scrape_kwargs=scrape_kwargs,
                cached_rows=cached_rows,
                allow_head_check=allow_head_check,
            )
        )
        _film_load_flights[flight_key] = task

        def _clear_finished(done_task, key=flight_key):
            if _film_load_flights.get(key) is done_task:
                _film_load_flights.pop(key, None)
            # Background stale refresh failures must be observed, but never replace
            # or invalidate the last known-good cache entry.
            with contextlib.suppress(asyncio.CancelledError):
                exc = done_task.exception()
                if exc is not None:
                    log.warning("background refresh FAILED %s/%s: %s", key[1], key[0], exc)

        task.add_done_callback(_clear_finished)
        return task, False


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
        entry = await asyncio.to_thread(
            pcache.get_with_freshness, ns, username, ttl=TTL_USER_FILMS
        )
        if entry is not None:
            cached, fresh = entry
            if fresh:
                log.warning("cache HIT  %s/%s (%d films)", list_type, username, len(cached))
                return _enriched_from_cache(cached), True

            # Stale-while-revalidate: kullanıcı sağlam eski sonucu hemen alır.
            # Yenileme başarısız/eksik olursa _scrape_enrich_and_cache cache'e yazmaz.
            full_entry = await asyncio.to_thread(
                pcache.get_with_freshness,
                "films_full_refresh",
                f"{list_type}:{username}",
                ttl=TTL_FULL_SCRAPE,
            )
            _task, joined = await _get_or_create_film_flight(
                username,
                list_type,
                enricher=enricher,
                pcache=pcache,
                scrape_kwargs=scrape_kwargs,
                cached_rows=cached,
                allow_head_check=bool(full_entry and full_entry[1]),
            )
            log.warning(
                "cache STALE %s/%s (%d films; refresh=%s)",
                list_type,
                username,
                len(cached),
                "joined" if joined else "started",
            )
            return _enriched_from_cache(cached), True

    # Aynı profil/liste eşzamanlı istenirse Letterboxd ve TMDb işini çoğaltma.
    # shield: bir istemci bağlantıyı kapattığında paylaşılan görev diğer bekleyenler
    # ve cache yazımı için çalışmaya devam eder.
    task, joined = await _get_or_create_film_flight(
        username,
        list_type,
        enricher=enricher,
        pcache=pcache,
        scrape_kwargs=scrape_kwargs,
    )
    if joined:
        log.warning("single-flight JOIN %s/%s", list_type, username)

    return await asyncio.shield(task)


_LETTERBOXD_USERNAME_RE = re.compile(r"^[a-z0-9_]{2,15}$")


def _normalize_username(value: str) -> str:
    """Normalize and validate a public Letterboxd profile name.

    Keeping usernames to a small URL-safe alphabet prevents path/query injection
    into scraper URLs and avoids wasting external API budget on malformed input.
    """
    if not isinstance(value, str):
        raise ValueError("Letterboxd kullanıcı adı metin olmalı.")
    username = value.strip().lstrip("@").lower()
    if not _LETTERBOXD_USERNAME_RE.fullmatch(username):
        raise ValueError(
            "Letterboxd kullanıcı adı 2–15 karakter olmalı; yalnızca harf, rakam "
            "veya alt çizgi içerebilir."
        )
    return username


class _UsernameRequest(BaseModel):
    @field_validator("username", mode="before", check_fields=False)
    @classmethod
    def validate_username(cls, value: str) -> str:
        return _normalize_username(value)


class RecommendRequest(_UsernameRequest):
    username: str


class RandomRequest(_UsernameRequest):
    username: str


class DeleteDataRequest(_UsernameRequest):
    username: str


class BlendRequest(BaseModel):
    username1: str
    username2: str

    @field_validator("username1", "username2", mode="before")
    @classmethod
    def validate_usernames(cls, value: str) -> str:
        return _normalize_username(value)


@app.get("/")
def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/api/health")
@app.head("/api/health", include_in_schema=False)
def health() -> dict:
    settings = get_settings()
    return {
        "status": "ok",
        "tmdb_enabled": settings.has_tmdb,
        "llm_enabled": settings.has_openai,
        "supabase_enabled": settings.has_supabase,
    }


@app.delete("/api/data")
async def delete_data(req: DeleteDataRequest, request: Request) -> dict:
    """Delete a username's regenerable profile and recommendation caches."""
    await _enforce_delete_rate_limit(request)
    settings = get_settings()

    # Stop this process from completing a stale profile refresh after deletion.
    async with _film_load_lock:
        flights = [
            _film_load_flights.pop(key)
            for key in list(_film_load_flights)
            if key[0] == req.username
        ]
    for flight in flights:
        flight.cancel()
    if flights:
        await asyncio.gather(*flights, return_exceptions=True)

    local_cache = Cache(settings.cache_db_path)
    local_ok = await asyncio.to_thread(
        _delete_cached_user_data, local_cache, req.username
    )
    remote_ok = True
    user_row_ok = True
    if settings.has_supabase:
        from supabase import create_client

        client = create_client(settings.supabase_url, settings.supabase_key)
        remote_cache = SupabaseCache(client)
        remote_ok, user_row_ok = await asyncio.gather(
            asyncio.to_thread(_delete_cached_user_data, remote_cache, req.username),
            asyncio.to_thread(delete_user, client, req.username),
        )

    if not (local_ok and remote_ok and user_row_ok):
        raise HTTPException(
            status_code=503,
            detail="Verinin tamamı silinemedi. Lütfen biraz sonra tekrar dene.",
        )
    log.warning("user data deleted username=%s", req.username)
    return {
        "ok": True,
        "username": req.username,
        "detail": "Kullanıcıya bağlı profil ve öneri cache'i silindi.",
    }


@app.post("/api/recommend")
async def recommend(req: RecommendRequest, request: Request):
    """SSE stream: queued? → scraping → enriching → ranking → llm → result."""
    global _q_waiting, _q_active
    await _enforce_heavy_rate_limit(request)

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
                    await asyncio.to_thread(upsert_user, supabase_client, req.username)
                enricher = Enricher(settings.tmdb_api_key, cache) if settings.has_tmdb else None

                watched_kwargs = dict(
                    delay=settings.scrape_delay,
                    max_pages=settings.watched_max_pages,
                    film_limit=settings.watched_film_limit,
                    max_retries=settings.scrape_max_retries,
                )
                watchlist_kwargs = dict(
                    delay=settings.scrape_delay,
                    max_pages=settings.scrape_max_pages,
                    film_limit=settings.watchlist_film_limit,
                    max_retries=settings.scrape_max_retries,
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
                        yield _scrape_error_event(exc)
                        return
                    raise exc
                (watched_films, w_cached), (watchlist_films, wl_cached) = hs["result"]
                load_ms = round((time.perf_counter() - t1) * 1000)
                yield _sse({"type": "step", "step": "enriching"})
                log.warning("⏱ load films      %.2fs  (watched=%d[cache=%s], watchlist=%d[cache=%s])",
                            time.perf_counter() - t1, len(watched_films), w_cached,
                            len(watchlist_films), wl_cached)

                if not watchlist_films:
                    yield _sse({"type": "error", "detail": "Watchlist boş veya gizli."})
                    return

                recommendation_key = _recommendation_cache_key(
                    req.username,
                    watched_films,
                    watchlist_films,
                    model=settings.openai_model if settings.has_openai else "local",
                    count=settings.num_recommendations,
                )
                cached_recommendation = await asyncio.to_thread(
                    pcache.get,
                    _recommendation_namespace(req.username),
                    recommendation_key,
                    ttl=TTL_RECOMMENDATION,
                ) if pcache is not None else None
                if cached_recommendation:
                    total_ms = round((time.perf_counter() - t0) * 1000)
                    metrics = {
                        "total_ms": total_ms,
                        "load_ms": load_ms,
                        "rank_ms": 0,
                        "llm_ms": 0,
                        "watched_cache_hit": w_cached,
                        "watchlist_cache_hit": wl_cached,
                        "recommendation_cache_hit": True,
                        "tmdb_api_calls": getattr(enricher, "_api_calls", 0),
                        "tmdb_l2_hydrated": getattr(enricher, "_l2_hydrated", 0),
                        "tmdb_l2_flushed": getattr(enricher, "_l2_flushed", 0),
                    }
                    log.warning("pipeline_metrics %s", json.dumps(metrics, sort_keys=True))
                    log.warning("recommendation cache HIT %s", req.username)
                    yield _sse({
                        "type": "result",
                        "username": req.username,
                        "watched_count": len(watched_films),
                        "watchlist_count": len(watchlist_films),
                        "taste_summary": cached_recommendation["taste_summary"],
                        "recommendations": cached_recommendation["recommendations"],
                        "meta": {
                            "tmdb_enabled": settings.has_tmdb,
                            "llm_used": cached_recommendation.get("llm_used", False),
                            "recommendation_cache_hit": True,
                            "metrics": metrics,
                        },
                    })
                    return

                # 3. TF-IDF ranking
                yield _sse({"type": "step", "step": "ranking"})
                t3 = time.perf_counter()
                if enricher is not None:
                    await enricher.ensure_details(_detail_sample(watched_films, 24))
                candidate_count = settings.num_recommendations * 2
                candidates = rank_watchlist(watched_films, watchlist_films, n=candidate_count)
                if enricher is not None:
                    await enricher.ensure_details(candidates)
                rank_ms = round((time.perf_counter() - t3) * 1000)
                log.warning("⏱ tfidf rank      %.2fs  (candidates=%d)", time.perf_counter() - t3, len(candidates))

                # 4. LLM
                yield _sse({"type": "step", "step": "llm"})
                t4 = time.perf_counter()
                result = await rank_candidates(settings, watched_films, candidates)
                llm_ms = round((time.perf_counter() - t4) * 1000)
                cacheable_result = result.get("llm_used", False) or not settings.has_openai
                if pcache is not None and result.get("recommendations") and cacheable_result:
                    await asyncio.to_thread(
                        pcache.set,
                        _recommendation_namespace(req.username),
                        recommendation_key,
                        result,
                    )
                log.warning("⏱ llm rerank      %.2fs  (llm_used=%s)", time.perf_counter() - t4, result.get("llm_used"))
                log.warning("⏱ TOTAL           %.2fs", time.perf_counter() - t0)

                metrics = {
                    "total_ms": round((time.perf_counter() - t0) * 1000),
                    "load_ms": load_ms,
                    "rank_ms": rank_ms,
                    "llm_ms": llm_ms,
                    "watched_cache_hit": w_cached,
                    "watchlist_cache_hit": wl_cached,
                    "recommendation_cache_hit": False,
                    "tmdb_api_calls": getattr(enricher, "_api_calls", 0),
                    "tmdb_cache_hits": getattr(enricher, "_cache_hits", 0),
                    "tmdb_rate_limits": getattr(enricher, "_rate_limits", 0),
                    "tmdb_l2_hydrated": getattr(enricher, "_l2_hydrated", 0),
                    "tmdb_l2_flushed": getattr(enricher, "_l2_flushed", 0),
                }
                log.warning("pipeline_metrics %s", json.dumps(metrics, sort_keys=True))

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
                        "recommendation_cache_hit": False,
                        "metrics": metrics,
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
async def random_pick(req: RandomRequest, request: Request):
    """SSE stream: watchlist'ten 3 rastgele film seç ve zenginleştir."""
    await _enforce_heavy_rate_limit(request)

    async def generate():
        settings = get_settings()
        supabase_client, cache = _make_cache(settings)
        pcache = _make_persistent_cache(settings, supabase_client)

        watchlist_kwargs = dict(
            delay=settings.scrape_delay,
            max_pages=settings.scrape_max_pages,
            film_limit=settings.watchlist_film_limit,
            max_retries=settings.scrape_max_retries,
        )

        # 0. Kalıcı cache'te zenginleştirilmiş watchlist varsa → scrape'siz seç
        entry = await asyncio.to_thread(
            pcache.get_with_freshness,
            "films_watchlist",
            req.username,
            ttl=TTL_USER_FILMS,
        ) if pcache else None
        if entry is not None:
            cached, fresh = entry
            if not fresh:
                enricher = Enricher(settings.tmdb_api_key, cache) if settings.has_tmdb else None
                full_entry = await asyncio.to_thread(
                    pcache.get_with_freshness,
                    "films_full_refresh",
                    f"watchlist:{req.username}",
                    ttl=TTL_FULL_SCRAPE,
                )
                await _get_or_create_film_flight(
                    req.username,
                    "watchlist",
                    enricher=enricher,
                    pcache=pcache,
                    scrape_kwargs=watchlist_kwargs,
                    cached_rows=cached,
                    allow_head_check=bool(full_entry and full_entry[1]),
                )
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
                **watchlist_kwargs,
            ),
            hr,
        ):
            yield ping
        if "error" in hr:
            exc = hr["error"]
            if isinstance(exc, ScrapeError):
                yield _scrape_error_event(exc)
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
        _capacity_stream(generate()),
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

    rating_signal_available = False
    if len(pairs) >= 3:
        r1 = np.array([p[0] for p in pairs])
        r2 = np.array([p[1] for p in pairs])
        # Pearson correlation: NaN güvenliği için std kontrolü
        if r1.std() > 0 and r2.std() > 0:
            rating_corr = float(np.corrcoef(r1, r2)[0, 1])
            rating_corr = max(rating_corr, 0.0)  # negatif korelasyon → 0 (ceza vermiyoruz)
            rating_signal_available = True

    # Genre ve era sinyalleri çok non-discriminating (herkes Drama/Comedy, herkes 2010s izliyor).
    # Keyword ve director gerçek zevk ayrımını yapar — ağırlıkları yükselt.
    if rating_signal_available:
        raw = (genre_sim * 0.04 + kw_sim * 0.37 + dir_sim * 0.37
               + era_sim * 0.02 + rating_corr * 0.20)
    else:
        raw = genre_sim * 0.05 + kw_sim * 0.47 + dir_sim * 0.47 + era_sim * 0.01

    # Kalibre skor: yapay taban/tavan yok; ağırlıklı benzerlik doğrudan 0–100'e
    # çevrilir. Skorun ne kadar güvenilir olduğu ayrıca raporlanır.
    score = round(max(0.0, min(raw, 1.0)) * 100)

    min_watched = min(len(watched1), len(watched2))

    def _metadata_coverage(films) -> float:
        if not films:
            return 0.0
        quality = [
            (0.25 if f.genres else 0.0)
            + (0.35 if f.keywords else 0.0)
            + (0.30 if f.director else 0.0)
            + (0.10 if f.year else 0.0)
            for f in films
        ]
        return sum(quality) / len(quality)

    sample_confidence = min(min_watched / 100.0, 1.0)
    metadata_confidence = (
        _metadata_coverage(watched1) + _metadata_coverage(watched2)
    ) / 2.0
    overlap_confidence = min(common_count / 10.0, 1.0)
    rating_confidence = min(len(pairs) / 8.0, 1.0)
    confidence_value = (
        sample_confidence * 0.45
        + metadata_confidence * 0.35
        + overlap_confidence * 0.10
        + rating_confidence * 0.10
    )
    confidence_score = round(max(0.0, min(confidence_value, 1.0)) * 100)
    if confidence_score >= 75:
        confidence_level = "high"
    elif confidence_score >= 45:
        confidence_level = "medium"
    else:
        confidence_level = "low"

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
        "confidence": {
            "level": confidence_level,
            "score": confidence_score,
            "sample_size": min_watched,
            "metadata_coverage": round(metadata_confidence * 100),
            "rating_pairs": len(pairs),
        },
        "common_count": common_count,
        "top_director": top_dir,
        "top_director_count1": directors1.get(top_dir, 0) if top_dir else 0,
        "top_director_count2": directors2.get(top_dir, 0) if top_dir else 0,
        "films": top_common,
    }


def _common_watchlist_films(first: list, second: list, limit: int = 3) -> list:
    """Match two watchlists by stable slug, falling back to normalized title/year."""
    second_slugs = {film.slug for film in second if film.slug}
    common = [film for film in first if film.slug and film.slug in second_slugs]
    seen_slugs = {film.slug for film in common}
    second_keys = {(film.title.lower().strip(), film.year) for film in second}
    common += [
        film
        for film in first
        if film.slug not in seen_slugs
        and (film.title.lower().strip(), film.year) in second_keys
    ]
    common.sort(
        key=lambda film: (film.poster_url is not None, film.vote_average),
        reverse=True,
    )
    return common[:limit]


@app.post("/api/blend")
async def blend(req: BlendRequest, request: Request):
    """SSE stream: iki kullanıcının film zevkini harmanlayıp uyum skoru hesapla."""
    await _enforce_heavy_rate_limit(request)
    log.warning("blend request: %s / %s", req.username1, req.username2)

    async def generate():
        t0 = time.perf_counter()
        settings = get_settings()
        try:
            supabase_client, cache = _make_cache(settings)
            pcache = _make_persistent_cache(settings, supabase_client)
            if supabase_client is not None:
                await asyncio.to_thread(upsert_user, supabase_client, req.username1)
                await asyncio.to_thread(upsert_user, supabase_client, req.username2)
            enricher = Enricher(settings.tmdb_api_key, cache) if settings.has_tmdb else None

            watched_kwargs = dict(
                delay=settings.scrape_delay, max_pages=settings.watched_max_pages,
                film_limit=settings.watched_film_limit, max_retries=settings.scrape_max_retries,
            )
            watchlist_kwargs = dict(
                delay=settings.scrape_delay, max_pages=settings.scrape_max_pages,
                film_limit=settings.watchlist_film_limit, max_retries=settings.scrape_max_retries,
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
                    yield _scrape_error_event(exc)
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

            # Watchlist'ler skor için gerekli değil. Arka planda başlatılır ve
            # ana Blend sonucu bekletilmeden ayrı bir SSE olayıyla tamamlanır.
            watchlist_future = asyncio.gather(
                _safe_load(req.username1, "watchlist", watchlist_kwargs),
                _safe_load(req.username2, "watchlist", watchlist_kwargs),
            )

            if enricher is not None:
                await asyncio.gather(
                    enricher.ensure_details(_detail_sample(w1_enriched, 40)),
                    enricher.ensure_details(_detail_sample(w2_enriched, 40)),
                )

            log.warning("blend profile load %.2fs  w1=%d w2=%d",
                        time.perf_counter() - t1, len(w1_enriched), len(w2_enriched))
            load_ms = round((time.perf_counter() - t1) * 1000)

            # ── Ranking ───────────────────────────────────────────────────────────
            yield _sse({"type": "step", "step": "ranking"})
            result = _calculate_blend(w1_enriched, w2_enriched, top_n=20)

            metrics = {
                "total_ms": round((time.perf_counter() - t0) * 1000),
                "load_ms": load_ms,
                "tmdb_api_calls": getattr(enricher, "_api_calls", 0),
                "tmdb_cache_hits": getattr(enricher, "_cache_hits", 0),
                "tmdb_rate_limits": getattr(enricher, "_rate_limits", 0),
                "tmdb_l2_hydrated": getattr(enricher, "_l2_hydrated", 0),
                "tmdb_l2_flushed": getattr(enricher, "_l2_flushed", 0),
            }
            log.warning("blend_metrics %s", json.dumps(metrics, sort_keys=True))

            log.warning("blend TOTAL %.2fs  score=%d common=%d",
                        time.perf_counter() - t0, result["score"], result["common_count"])

            yield _sse({
                "type": "result",
                "username1": req.username1,
                "username2": req.username2,
                "score": result["score"],
                "confidence": result["confidence"],
                "watched_count1": len(w1_enriched),
                "watched_count2": len(w2_enriched),
                "common_count": result["common_count"],
                "top_director": result["top_director"],
                "top_director_count1": result["top_director_count1"],
                "top_director_count2": result["top_director_count2"],
                "films": [f.to_dict() for f in result["films"]],
                "common_watchlist_films": [],
                "watchlist_public": None,
                "watchlist_pending": True,
                "meta": {"metrics": metrics},
            })

            # ── Faz 2: ortak watchlist (lazy, ana sonuçtan sonra) ────────────────
            h2: dict = {}
            async for ping in _await_with_heartbeat(watchlist_future, h2):
                yield ping
            if "error" in h2:
                log.warning("blend watchlist load failed: %s", h2["error"])
                wl1e, wl2e = [], []
            else:
                (wl1e, _w1), (wl2e, _w2) = h2["result"]
            common_wl_films = _common_watchlist_films(wl1e, wl2e)
            yield _sse({
                "type": "watchlist_result",
                "common_watchlist_films": [film.to_dict() for film in common_wl_films],
                "watchlist_public": bool(wl1e) and bool(wl2e),
                "metrics": {
                    "watchlist_ms": round((time.perf_counter() - t0) * 1000),
                    "watchlist_count1": len(wl1e),
                    "watchlist_count2": len(wl2e),
                },
            })

        except Exception as exc:
            log.warning("blend EXCEPTION %s: %s", type(exc).__name__, exc)
            yield _sse({"type": "error", "detail": "Beklenmeyen bir hata oluştu."})

    return StreamingResponse(
        _capacity_stream(generate()),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
