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
import secrets
import time
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, field_validator

from .config import get_settings
from .auth import (
    Account,
    AccountExistsError,
    AuthError,
    AuthService,
    BlendServiceError,
    InvalidCredentialsError,
    RecommendationFeedbackError,
    VerificationError,
    validate_password,
)
from .cache import Cache, LayeredCache
from .database import delete_user, upsert_user, SupabaseCache
from .enrich import Enricher, EnrichedFilm, close_tmdb_client
from .llm import rank_candidates
from .recommender import rank_watchlist
from .rate_limit import SlidingWindowRateLimiter
from .scraper import (
    AccessBlockedError,
    ScrapeError,
    scrape_diary,
    scrape_films,
    scrape_profile,
    scrape_recent_watched,
    scrape_watchlist,
    scrape_watched,
)
from .taste_profile import (
    TASTE_PROFILE_VERSION,
    build_taste_profile,
    taste_source_fingerprint,
)
from . import profile_sync


@contextlib.asynccontextmanager
async def _lifespan(_app):
    yield
    await close_tmdb_client()


app = FastAPI(title="Letterboxd AI Recommender", version="0.4.0", lifespan=_lifespan)
log = logging.getLogger("moviebox")

_allowed_origins = os.environ.get("ALLOWED_ORIGINS", "*").split(",")
app.add_middleware(
    CORSMiddleware,
    allow_origins=_allowed_origins,
    allow_methods=["GET", "POST", "DELETE"],
    allow_headers=["Content-Type", "X-CSRF-Token"],
    allow_credentials="*" not in _allowed_origins,
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
_auth_rate_limiter = SlidingWindowRateLimiter(
    limit=8,
    window_seconds=15 * 60,
    burst=3,
    burst_seconds=30,
)
_feedback_rate_limiter = SlidingWindowRateLimiter(
    limit=120,
    window_seconds=60 * 60,
    burst=20,
    burst_seconds=60,
)
_readiness_lock = asyncio.Lock()
_readiness_cache = {"checked_at": 0.0, "ready": False}

ACCESS_COOKIE = "mb_access"
REFRESH_COOKIE = "mb_refresh"
CSRF_COOKIE = "mb_csrf"


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


async def _enforce_auth_rate_limit(request: Request) -> None:
    allowed, retry_after = await _auth_rate_limiter.check(_client_ip(request))
    if not allowed:
        raise HTTPException(
            status_code=429,
            detail="Çok fazla hesap isteği gönderildi. Lütfen biraz sonra tekrar dene.",
            headers={"Retry-After": str(retry_after)},
        )


async def _enforce_feedback_rate_limit(request: Request) -> None:
    allowed, retry_after = await _feedback_rate_limiter.check(_client_ip(request))
    if not allowed:
        raise HTTPException(
            status_code=429,
            detail="Çok fazla öneri tercihi gönderildi. Lütfen biraz sonra tekrar dene.",
            headers={"Retry-After": str(retry_after)},
        )


def _auth_service():
    settings = get_settings()
    if not getattr(settings, "has_auth", False):
        raise HTTPException(status_code=503, detail="Hesap sistemi yapılandırılmamış.")
    return AuthService(settings)


def _ip_hash(request: Request) -> str:
    settings = get_settings()
    return hashlib.sha256(
        f"{settings.auth_identity_secret}:{_client_ip(request)}".encode("utf-8")
    ).hexdigest()


def _set_session_cookies(response: Response, session) -> str:
    settings = get_settings()
    access_age = max(60, min(int(session.expires_in), settings.auth_session_max_age))
    shared = {
        "secure": settings.auth_cookie_secure,
        "samesite": "lax",
        "path": "/",
    }
    response.set_cookie(
        ACCESS_COOKIE,
        session.access_token,
        max_age=access_age,
        httponly=True,
        **shared,
    )
    response.set_cookie(
        REFRESH_COOKIE,
        session.refresh_token,
        max_age=settings.auth_session_max_age,
        httponly=True,
        **shared,
    )
    csrf_token = secrets.token_urlsafe(32)
    response.set_cookie(
        CSRF_COOKIE,
        csrf_token,
        max_age=settings.auth_session_max_age,
        httponly=False,
        **shared,
    )
    return csrf_token


def _clear_session_cookies(response: Response) -> None:
    settings = get_settings()
    for key in (ACCESS_COOKIE, REFRESH_COOKIE, CSRF_COOKIE):
        response.delete_cookie(
            key,
            path="/",
            secure=settings.auth_cookie_secure,
            samesite="lax",
        )


def _require_csrf(request: Request) -> None:
    cookie = request.cookies.get(CSRF_COOKIE, "")
    header = request.headers.get("x-csrf-token", "")
    if not cookie or not header or not secrets.compare_digest(cookie, header):
        raise HTTPException(status_code=403, detail="Güvenlik doğrulaması başarısız.")


async def _require_account(request: Request) -> Account:
    access_token = request.cookies.get(ACCESS_COOKIE, "")
    if not access_token:
        raise HTTPException(status_code=401, detail="Oturum açman gerekiyor.")
    try:
        return await asyncio.to_thread(
            _auth_service().current_account, access_token
        )
    except InvalidCredentialsError as exc:
        raise HTTPException(status_code=401, detail="Oturum geçersiz.") from exc


async def _enforce_account_username(request: Request, username: str) -> Account | None:
    """Protect legacy username payloads once account mode is enabled."""
    if not getattr(get_settings(), "has_auth", False):
        return None
    _require_csrf(request)
    account = await _require_account(request)
    if account.username != username:
        raise HTTPException(status_code=403, detail="Yalnızca kendi profilini kullanabilirsin.")
    return account


def _raise_auth_http(exc: Exception) -> None:
    if isinstance(exc, AccountExistsError):
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if isinstance(exc, InvalidCredentialsError):
        raise HTTPException(status_code=401, detail="Kullanıcı adı veya parola hatalı.") from exc
    if isinstance(exc, VerificationError):
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if isinstance(exc, AuthError):
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    raise exc


def _raise_blend_http(exc: BlendServiceError) -> None:
    code = str(exc)
    errors = {
        "recipient_not_found": (404, "Kayıtlı Movieboxd kullanıcısı bulunamadı."),
        "self_request": (422, "Kendine Blend isteği gönderemezsin."),
        "blend_request_exists": (409, "Bu iki kullanıcı arasında bekleyen bir istek var."),
        "pending_quota_reached": (429, "Bekleyen Blend isteği kotasına ulaştın."),
        "blend_user_blocked": (403, "Bu kullanıcıyla Blend isteği oluşturulamaz."),
        "request_not_found": (404, "Blend isteği bulunamadı."),
        "forbidden": (403, "Bu Blend isteği için yetkin yok."),
        "request_already_decided": (409, "Bu Blend isteği daha önce sonuçlandırılmış."),
        "request_not_cancellable": (409, "Bu Blend isteği artık iptal edilemez."),
        "accepted_request_not_found": (409, "Kabul edilmiş Blend isteği bulunamadı."),
        "blend_result_save_failed": (503, "Blend sonucu kaydedilemedi."),
        "user_not_found": (404, "Kayıtlı Movieboxd kullanıcısı bulunamadı."),
        "self_block": (422, "Kendini engelleyemezsin."),
        "self_report": (422, "Kendini bildiremezsin."),
        "invalid_report_category": (422, "Geçersiz bildirim kategorisi."),
        "report_quota_reached": (429, "Günlük bildirim kotasına ulaştın."),
        "block_failed": (400, "Kullanıcı engellenemedi."),
        "unblock_failed": (400, "Engel kaldırılamadı."),
        "report_failed": (400, "Bildirim gönderilemedi."),
    }
    status_code, detail = errors.get(code, (400, "Blend işlemi tamamlanamadı."))
    raise HTTPException(status_code=status_code, detail=detail) from exc


def _raise_feedback_http(exc: RecommendationFeedbackError) -> None:
    errors = {
        "invalid_feedback_action": (422, "Geçersiz öneri geri bildirimi."),
        "invalid_film": (422, "Film bilgisi geçersiz."),
        "active_account_not_found": (403, "Aktif hesap bulunamadı."),
        "feedback_save_failed": (503, "Geri bildirim kaydedilemedi."),
        "feedback_undo_failed": (503, "Geri bildirim geri alınamadı."),
        "feedback_history_failed": (503, "Öneri geçmişi yüklenemedi."),
        "feedback_filter_failed": (503, "Öneri tercihleri yüklenemedi."),
    }
    status_code, detail = errors.get(str(exc), (400, "Geri bildirim işlenemedi."))
    raise HTTPException(status_code=status_code, detail=detail) from exc


def _raise_scrape_http(exc: ScrapeError) -> None:
    if isinstance(exc, AccessBlockedError):
        raise HTTPException(
            status_code=503,
            detail=(
                "Letterboxd erişimi geçici olarak sınırladı. Otomatik yeniden "
                "denemeler tamamlandı; lütfen yaklaşık bir dakika sonra tekrar dene."
            ),
            headers={"Retry-After": "60"},
        ) from exc
    raise HTTPException(status_code=exc.status or 503, detail=str(exc)) from exc


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
BLEND_VERSION = "blend-v2-calibrated"


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


class RegisterStartRequest(_UsernameRequest):
    username: str
    password: str
    password_confirm: str


class OwnershipVerifyRequest(_UsernameRequest):
    username: str
    code: str


class LoginRequest(_UsernameRequest):
    username: str
    password: str


class PasswordResetStartRequest(_UsernameRequest):
    username: str


class PasswordResetFinishRequest(_UsernameRequest):
    username: str
    code: str
    new_password: str
    new_password_confirm: str


class CreateBlendRequest(BaseModel):
    recipient_username: str

    @field_validator("recipient_username", mode="before")
    @classmethod
    def validate_recipient(cls, value: str) -> str:
        return _normalize_username(value)


class BlendDecisionRequest(BaseModel):
    decision: str

    @field_validator("decision", mode="before")
    @classmethod
    def validate_decision(cls, value: str) -> str:
        decision = str(value).strip().lower()
        if decision not in {"accepted", "rejected"}:
            raise ValueError("Karar accepted veya rejected olmalı.")
        return decision


class ReportUserRequest(BaseModel):
    category: str
    detail: str = ""

    @field_validator("category", mode="before")
    @classmethod
    def validate_category(cls, value: str) -> str:
        category = str(value).strip().lower()
        if category not in {"spam", "harassment", "impersonation", "other"}:
            raise ValueError("Geçersiz bildirim kategorisi.")
        return category

    @field_validator("detail", mode="before")
    @classmethod
    def validate_detail(cls, value: str) -> str:
        detail = str(value or "").strip()
        if len(detail) > 500:
            raise ValueError("Bildirim detayı en fazla 500 karakter olabilir.")
        return detail


_FILM_SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,159}$")


class RecommendationFeedbackRequest(BaseModel):
    slug: str
    title: str
    tmdb_id: int | None = None
    poster_url: str | None = None
    action: str

    @field_validator("slug", mode="before")
    @classmethod
    def validate_slug(cls, value: str) -> str:
        slug = str(value or "").strip().lower()
        if not _FILM_SLUG_RE.fullmatch(slug):
            raise ValueError("Geçersiz film kimliği.")
        return slug

    @field_validator("title", mode="before")
    @classmethod
    def validate_title(cls, value: str) -> str:
        title = str(value or "").strip()
        if not 1 <= len(title) <= 300:
            raise ValueError("Film adı 1–300 karakter olmalı.")
        return title

    @field_validator("tmdb_id", mode="before")
    @classmethod
    def validate_tmdb_id(cls, value):
        if value in (None, ""):
            return None
        parsed = int(value)
        if parsed <= 0:
            raise ValueError("Geçersiz TMDb kimliği.")
        return parsed

    @field_validator("poster_url", mode="before")
    @classmethod
    def validate_poster_url(cls, value):
        if value in (None, ""):
            return None
        url = str(value).strip()
        if len(url) > 1000 or not url.startswith("https://"):
            raise ValueError("Geçersiz poster adresi.")
        return url

    @field_validator("action", mode="before")
    @classmethod
    def validate_action(cls, value: str) -> str:
        action = str(value or "").strip().lower()
        if action not in {"watch", "skip", "block"}:
            raise ValueError("Geçersiz öneri geri bildirimi.")
        return action


def _filter_suppressed_films(films: list, suppressed_slugs: set[str]) -> list:
    if not suppressed_slugs:
        return list(films)
    return [film for film in films if getattr(film, "slug", "") not in suppressed_slugs]


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
        "auth_enabled": getattr(settings, "has_auth", False),
    }


@app.get("/api/readiness")
@app.head("/api/readiness", include_in_schema=False)
async def readiness(response: Response) -> dict:
    """Check that auth configuration and the required Supabase schema are usable."""
    settings = get_settings()
    if not settings.has_auth:
        response.status_code = 503
        return {"status": "not_ready", "auth_configured": False, "schema_ready": False}

    now = time.monotonic()
    ttl = 60 if _readiness_cache["ready"] else 15
    if now - _readiness_cache["checked_at"] < ttl:
        ready = bool(_readiness_cache["ready"])
    else:
        async with _readiness_lock:
            now = time.monotonic()
            ttl = 60 if _readiness_cache["ready"] else 15
            if now - _readiness_cache["checked_at"] >= ttl:
                try:
                    ready = await asyncio.to_thread(_auth_service().check_schema)
                except Exception as exc:
                    log.warning("readiness schema check failed: %s", type(exc).__name__)
                    ready = False
                _readiness_cache.update(checked_at=now, ready=bool(ready))
            else:
                ready = bool(_readiness_cache["ready"])
    if not ready:
        response.status_code = 503
    return {
        "status": "ready" if ready else "not_ready",
        "auth_configured": True,
        "schema_ready": ready,
    }


@app.post("/api/auth/register/start")
async def register_start(req: RegisterStartRequest, request: Request) -> dict:
    await _enforce_auth_rate_limit(request)
    try:
        validate_password(req.password, req.password_confirm)
        profile = await scrape_profile(
            req.username, max_retries=get_settings().scrape_max_retries
        )
        challenge = await asyncio.to_thread(
            _auth_service().start_registration,
            req.username,
            req.password,
            profile,
            ip_hash=_ip_hash(request),
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except ScrapeError as exc:
        _raise_scrape_http(exc)
    except AuthError as exc:
        _raise_auth_http(exc)
    return {
        "username": challenge.username,
        "verification_code": challenge.verification_code,
        "expires_at": challenge.expires_at,
        "instruction": "Kodu Letterboxd profil bio alanına ekleyip doğrula.",
    }


@app.post("/api/auth/register/verify")
async def register_verify(req: OwnershipVerifyRequest, request: Request) -> dict:
    await _enforce_auth_rate_limit(request)
    try:
        profile = await scrape_profile(
            req.username, max_retries=get_settings().scrape_max_retries
        )
        account = await asyncio.to_thread(
            _auth_service().verify_ownership,
            req.username,
            req.code.strip(),
            profile,
            ip_hash=_ip_hash(request),
        )
    except ScrapeError as exc:
        _raise_scrape_http(exc)
    except AuthError as exc:
        _raise_auth_http(exc)
    return {"ok": True, "account": account.__dict__}


@app.post("/api/auth/login")
async def login(req: LoginRequest, request: Request, response: Response) -> dict:
    await _enforce_auth_rate_limit(request)
    try:
        session = await asyncio.to_thread(
            _auth_service().login,
            req.username,
            req.password,
            ip_hash=_ip_hash(request),
        )
    except AuthError as exc:
        _raise_auth_http(exc)
    _set_session_cookies(response, session)
    return {"ok": True, "account": session.account.__dict__}


@app.get("/api/auth/me")
async def auth_me(request: Request) -> dict:
    account = await _require_account(request)
    return {"account": account.__dict__}


@app.post("/api/auth/refresh")
async def refresh_session(request: Request, response: Response) -> dict:
    _require_csrf(request)
    refresh_token = request.cookies.get(REFRESH_COOKIE, "")
    if not refresh_token:
        raise HTTPException(status_code=401, detail="Oturum yenilenemedi.")
    try:
        session = await asyncio.to_thread(_auth_service().refresh, refresh_token)
    except AuthError as exc:
        _clear_session_cookies(response)
        _raise_auth_http(exc)
    _set_session_cookies(response, session)
    return {"ok": True, "account": session.account.__dict__}


@app.post("/api/auth/logout")
async def logout(request: Request, response: Response) -> dict:
    _require_csrf(request)
    access_token = request.cookies.get(ACCESS_COOKIE, "")
    refresh_token = request.cookies.get(REFRESH_COOKIE, "")
    if access_token and refresh_token:
        await asyncio.to_thread(
            _auth_service().revoke, access_token, refresh_token
        )
    _clear_session_cookies(response)
    return {"ok": True}


@app.post("/api/auth/password-reset/start")
async def password_reset_start(
    req: PasswordResetStartRequest, request: Request
) -> dict:
    await _enforce_auth_rate_limit(request)
    try:
        challenge = await asyncio.to_thread(
            _auth_service().start_password_reset,
            req.username,
            ip_hash=_ip_hash(request),
        )
    except AuthError as exc:
        _raise_auth_http(exc)
    return {
        "username": challenge.username,
        "verification_code": challenge.verification_code,
        "expires_at": challenge.expires_at,
        "instruction": "Kodu Letterboxd profil bio alanına ekleyip yeni parolanı belirle.",
    }


@app.post("/api/auth/password-reset/finish")
async def password_reset_finish(
    req: PasswordResetFinishRequest, request: Request
) -> dict:
    await _enforce_auth_rate_limit(request)
    try:
        validate_password(req.new_password, req.new_password_confirm)
        profile = await scrape_profile(
            req.username, max_retries=get_settings().scrape_max_retries
        )
        await asyncio.to_thread(
            _auth_service().finish_password_reset,
            req.username,
            req.code.strip(),
            req.new_password,
            profile,
            ip_hash=_ip_hash(request),
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except ScrapeError as exc:
        _raise_scrape_http(exc)
    except AuthError as exc:
        _raise_auth_http(exc)
    return {"ok": True}


@app.get("/api/profile/me")
async def profile_me(request: Request) -> dict:
    account = await _require_account(request)
    service = _auth_service()
    profile = await asyncio.to_thread(service.get_profile, account)
    profile["needs_refresh"] = bool(
        not profile.get("taste")
        or profile["taste"].get("algorithm_version") != TASTE_PROFILE_VERSION
    )
    with contextlib.suppress(Exception):
        job = await asyncio.to_thread(service.get_sync_job, account.id)
        profile["sync_job"] = profile_sync.progress_of(job)
        if not profile_sync.is_running(account.id):
            if profile_sync.job_is_resumable(job):
                # Resume-on-visit: a job whose heartbeat went stale (instance
                # restart) is picked up here without any external scheduler.
                profile_sync.start(_SyncPipeline(get_settings()), service, account)
            elif profile_sync.incremental_due(job):
                # Completed sweep gone stale → cheap "what did they watch since"
                # refresh in the background.
                job = await profile_sync.ensure_started(
                    _SyncPipeline(get_settings()), service, account, scope="incremental"
                )
                profile["sync_job"] = profile_sync.progress_of(job)
    return profile


@app.post("/api/recommendations/feedback")
async def save_recommendation_feedback(
    req: RecommendationFeedbackRequest, request: Request
) -> dict:
    _require_csrf(request)
    await _enforce_feedback_rate_limit(request)
    account = await _require_account(request)
    try:
        feedback = await asyncio.to_thread(
            _auth_service().set_recommendation_feedback,
            account,
            {
                "slug": req.slug,
                "title": req.title,
                "tmdb_id": req.tmdb_id,
                "poster_url": req.poster_url,
            },
            req.action,
        )
    except RecommendationFeedbackError as exc:
        _raise_feedback_http(exc)
    return {"ok": True, "feedback": feedback}


@app.delete("/api/recommendations/feedback/{film_slug}")
async def undo_recommendation_feedback(film_slug: str, request: Request) -> dict:
    _require_csrf(request)
    await _enforce_feedback_rate_limit(request)
    account = await _require_account(request)
    slug = film_slug.strip().lower()
    if not _FILM_SLUG_RE.fullmatch(slug):
        raise HTTPException(status_code=422, detail="Geçersiz film kimliği.")
    try:
        undone = await asyncio.to_thread(
            _auth_service().undo_recommendation_feedback, account, slug
        )
    except RecommendationFeedbackError as exc:
        _raise_feedback_http(exc)
    return {"ok": True, "undone": undone, "film_slug": slug}


@app.get("/api/recommendations/history")
async def recommendation_history(request: Request) -> dict:
    account = await _require_account(request)
    try:
        return await asyncio.to_thread(
            _auth_service().list_recommendation_history, account
        )
    except RecommendationFeedbackError as exc:
        _raise_feedback_http(exc)


async def _provisional_profile_sync(
    account: Account, settings, service, *, force: bool
) -> dict:
    """The fast in-request pass: identity + Fav 4 + last-N watched → snapshot.

    This is the pre-existing behaviour; it keeps the profile useful within one
    request while the full watched-history sweep runs in the background.
    """
    await asyncio.to_thread(service.mark_sync_status, account.id, "syncing")
    try:
        profile = await scrape_profile(
            account.username, max_retries=settings.scrape_max_retries
        )
        supabase_client, cache = _make_cache(settings)
        pcache = _make_persistent_cache(settings, supabase_client)
        enricher = Enricher(settings.tmdb_api_key, cache) if settings.has_tmdb else None
        watched, _from_cache = await _load_user_films(
            account.username,
            "watched",
            settings=settings,
            enricher=enricher,
            pcache=pcache,
            scrape_kwargs={
                "delay": settings.scrape_delay,
                "max_pages": settings.watched_max_pages,
                "film_limit": settings.watched_film_limit,
                "max_retries": settings.scrape_max_retries,
            },
            force=force,
        )
        source_fingerprint = taste_source_fingerprint(profile, watched)
        stored = await asyncio.to_thread(service.get_profile, account)
        if (
            stored.get("taste")
            and stored["taste"].get("source_fingerprint") == source_fingerprint
            and stored["taste"].get("algorithm_version") == TASTE_PROFILE_VERSION
        ):
            await asyncio.to_thread(service.mark_sync_status, account.id, "ready")
            account.profile_sync_status = "ready"
            stored["account"] = account.__dict__
            return stored
        if enricher is not None:
            await enricher.ensure_details(_detail_sample(watched, 40))
            favorites = await enricher.enrich(
                profile.favorite_films, include_details=False
            )
        else:
            favorites = [
                EnrichedFilm(
                    title=film.title,
                    year=film.year,
                    slug=film.slug,
                    poster_url=film.poster_url,
                )
                for film in profile.favorite_films
            ]
        taste = build_taste_profile(watched)
        taste.source_fingerprint = source_fingerprint
        await asyncio.to_thread(
            service.save_profile_snapshot,
            account,
            profile,
            favorites,
            taste,
        )
        account.display_name = profile.display_name
        account.avatar_url = profile.avatar_url or ""
        account.profile_sync_status = "ready"
        return {
            "account": account.__dict__,
            "taste": taste.to_dict(),
            "favorite_films": [film.to_dict() for film in favorites[:4]],
        }
    except ScrapeError as exc:
        with contextlib.suppress(Exception):
            await asyncio.to_thread(service.mark_sync_status, account.id, "failed")
        _raise_scrape_http(exc)
    except HTTPException:
        raise
    except Exception as exc:
        log.warning("profile sync failed username=%s: %s", account.username, exc)
        with contextlib.suppress(Exception):
            await asyncio.to_thread(service.mark_sync_status, account.id, "failed")
        raise HTTPException(
            status_code=503,
            detail="Profil senkronu tamamlanamadı. Son sağlam analiz korunuyor.",
        ) from exc


class _SyncPipeline:
    """Glue the background runner (app.profile_sync) calls for the full sweep."""

    window_pages = profile_sync.WATCHED_WINDOW_PAGES

    def __init__(self, settings):
        self.settings = settings
        self._enricher_obj = None
        self._enricher_built = False

    def _enricher(self):
        if not self._enricher_built:
            self._enricher_built = True
            if self.settings.has_tmdb:
                _client, cache = _make_cache(self.settings)
                self._enricher_obj = Enricher(self.settings.tmdb_api_key, cache)
        return self._enricher_obj

    async def scrape_watched_window(self, username: str, start_page: int) -> list[dict]:
        films, _complete = await scrape_films(
            username,
            start_page=start_page,
            max_pages=self.window_pages,
            film_limit=self.window_pages * 80,
            max_retries=self.settings.scrape_max_retries,
        )
        return [
            {
                "slug": film.slug,
                "title": film.title,
                "year": film.year,
                "user_rating": film.user_rating,
            }
            for film in films
            if film.slug
        ]

    async def scrape_recent(self, username: str) -> list[dict]:
        films = await scrape_recent_watched(
            username, max_retries=self.settings.scrape_max_retries
        )
        return [
            {
                "slug": film.slug,
                "title": film.title,
                "year": film.year,
                "user_rating": film.user_rating,
            }
            for film in films
            if film.slug
        ]

    async def enrich_search(self, films: list[dict]) -> list[dict]:
        enricher = self._enricher()
        if enricher is None:
            return [
                {
                    "slug": film["slug"],
                    "title": film.get("title") or "",
                    "release_year": film.get("year"),
                    "user_rating": film.get("user_rating"),
                    "watched_rank": film.get("watched_rank"),
                    "details_loaded": False,
                }
                for film in films
            ]
        enriched = await enricher.enrich(
            [
                {
                    "slug": film["slug"],
                    "title": film.get("title") or "",
                    "year": film.get("year"),
                    "user_rating": film.get("user_rating"),
                }
                for film in films
            ],
            include_details=False,
        )
        out: list[dict] = []
        for src, ef in zip(films, enriched):
            out.append(
                {
                    "slug": src["slug"],
                    "title": ef.title or src.get("title") or "",
                    "release_year": ef.year or src.get("year"),
                    "tmdb_id": ef.tmdb_id,
                    "genres": ef.genres or [],
                    "poster_url": ef.poster_url or "",
                    "user_rating": src.get("user_rating"),
                    "watched_rank": src.get("watched_rank"),
                    "details_loaded": False,
                }
            )
        return out

    async def enrich_details(self, rows: list[dict]) -> list[dict]:
        enricher = self._enricher()
        if enricher is None:
            return []
        films = [
            EnrichedFilm(
                title=row.get("title") or "",
                year=row.get("release_year"),
                slug=row.get("film_slug") or row.get("slug") or "",
                tmdb_id=row.get("tmdb_id"),
            )
            for row in rows
            if row.get("tmdb_id") and (row.get("film_slug") or row.get("slug"))
        ]
        detailed = await enricher.ensure_details(films)
        return [
            {
                "slug": film.slug,
                "director": film.director or "",
                "genres": film.genres or [],
                "keywords": film.keywords or [],
                "details_loaded": bool(film.details_loaded),
            }
            for film in detailed
            if film.slug
        ]

    async def rebuild_snapshot(self, account: Account) -> int:
        service = _auth_service()
        rows = await asyncio.to_thread(service.get_watched_films, account.id)
        rows.sort(
            key=lambda row: row["watched_rank"]
            if row.get("watched_rank") is not None
            else 10**9
        )
        watched = [
            EnrichedFilm(
                title=row.get("title") or "",
                year=row.get("release_year"),
                slug=row.get("film_slug") or "",
                tmdb_id=row.get("tmdb_id"),
                genres=row.get("genres") or [],
                director=row.get("director") or "",
                keywords=row.get("keywords") or [],
                details_loaded=bool(row.get("details_loaded")),
                user_rating=row.get("user_rating"),
            )
            for row in rows
        ]
        profile = await scrape_profile(
            account.username, max_retries=self.settings.scrape_max_retries
        )
        enricher = self._enricher()
        if enricher is not None:
            favorites = await enricher.enrich(
                profile.favorite_films, include_details=False
            )
        else:
            favorites = [
                EnrichedFilm(
                    title=film.title,
                    year=film.year,
                    slug=film.slug,
                    poster_url=film.poster_url,
                )
                for film in profile.favorite_films
            ]
        taste = build_taste_profile(watched)
        taste.source_fingerprint = taste_source_fingerprint(profile, watched)
        await asyncio.to_thread(
            service.save_profile_snapshot, account, profile, favorites, taste
        )
        return len(watched)


@app.post("/api/profile/sync")
async def sync_my_profile(request: Request, force: bool = False) -> dict:
    _require_csrf(request)
    await _enforce_heavy_rate_limit(request)
    account = await _require_account(request)
    settings = get_settings()
    service = _auth_service()
    try:
        await asyncio.to_thread(service.check_schema)
    except Exception as exc:
        raise HTTPException(
            status_code=503,
            detail="Profil veri şeması güncelleniyor. Lütfen biraz sonra tekrar dene.",
        ) from exc

    full_sync_available = True
    try:
        await asyncio.to_thread(service.check_sync_schema)
    except Exception:
        full_sync_available = False

    # Once the full history has been analysed once, never regress to the
    # 100-film in-request pass — just serve the stored snapshot.
    if full_sync_available and not force:
        job = await asyncio.to_thread(service.get_sync_job, account.id)
        if job and job.get("state") == "done" and job.get("scope") == "full":
            stored = await asyncio.to_thread(service.get_profile, account)
            stored["account"] = account.__dict__
            stored["sync_job"] = profile_sync.progress_of(job)
            with contextlib.suppress(Exception):
                await asyncio.to_thread(service.mark_sync_status, account.id, "ready")
            return stored

    result = await _provisional_profile_sync(account, settings, service, force=force)

    if full_sync_available:
        with contextlib.suppress(Exception):
            job = await profile_sync.ensure_started(
                _SyncPipeline(settings), service, account, scope="full", force=force
            )
            result["sync_job"] = profile_sync.progress_of(job)
    return result


@app.get("/api/users/search")
async def search_registered_users(q: str, request: Request) -> dict:
    account = await _require_account(request)
    try:
        query = _normalize_username(q)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    users = await asyncio.to_thread(
        _auth_service().search_accounts, account, query
    )
    return {"users": users}


@app.post("/api/users/{username}/block")
async def block_registered_user(username: str, request: Request) -> dict:
    _require_csrf(request)
    await _enforce_auth_rate_limit(request)
    account = await _require_account(request)
    try:
        normalized = _normalize_username(username)
        await asyncio.to_thread(_auth_service().block_user, account, normalized)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except BlendServiceError as exc:
        _raise_blend_http(exc)
    return {"ok": True, "username": normalized, "blocked": True}


@app.delete("/api/users/{username}/block")
async def unblock_registered_user(username: str, request: Request) -> dict:
    _require_csrf(request)
    account = await _require_account(request)
    try:
        normalized = _normalize_username(username)
        await asyncio.to_thread(_auth_service().unblock_user, account, normalized)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except BlendServiceError as exc:
        _raise_blend_http(exc)
    return {"ok": True, "username": normalized, "blocked": False}


@app.post("/api/users/{username}/report")
async def report_registered_user(
    username: str, req: ReportUserRequest, request: Request
) -> dict:
    _require_csrf(request)
    await _enforce_auth_rate_limit(request)
    account = await _require_account(request)
    try:
        normalized = _normalize_username(username)
        report_id = await asyncio.to_thread(
            _auth_service().report_user,
            account,
            normalized,
            req.category,
            req.detail,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except BlendServiceError as exc:
        _raise_blend_http(exc)
    return {"ok": True, "report_id": report_id}


@app.post("/api/blends/requests")
async def create_blend_invite(req: CreateBlendRequest, request: Request) -> dict:
    _require_csrf(request)
    await _enforce_auth_rate_limit(request)
    account = await _require_account(request)
    try:
        request_id = await asyncio.to_thread(
            _auth_service().create_blend_request,
            account,
            req.recipient_username,
            ip_hash=_ip_hash(request),
        )
    except BlendServiceError as exc:
        _raise_blend_http(exc)
    return {
        "ok": True,
        "request_id": request_id,
        "recipient_username": req.recipient_username,
        "status": "pending",
    }


@app.get("/api/blends")
async def list_my_blends(request: Request) -> dict:
    account = await _require_account(request)
    return await asyncio.to_thread(_auth_service().list_blends, account)


@app.delete("/api/blends/requests/{request_id}")
async def cancel_blend_invite(request_id: str, request: Request) -> dict:
    _require_csrf(request)
    account = await _require_account(request)
    try:
        await asyncio.to_thread(
            _auth_service().cancel_blend_request, account, request_id
        )
    except BlendServiceError as exc:
        _raise_blend_http(exc)
    return {"ok": True, "request_id": request_id, "status": "cancelled"}


async def _compute_accepted_blend(
    account: Account, request_id: str, service: AuthService
) -> dict:
    stored = await asyncio.to_thread(service.get_blend_result, request_id)
    if stored is not None:
        return {**stored["result"], "request_id": request_id, "cached": True}

    _request, first, second = await asyncio.to_thread(
        service.get_blend_participants, account, request_id
    )
    settings = get_settings()
    supabase_client, cache = _make_cache(settings)
    pcache = _make_persistent_cache(settings, supabase_client)
    enricher = Enricher(settings.tmdb_api_key, cache) if settings.has_tmdb else None
    watched_kwargs = {
        "delay": settings.scrape_delay,
        "max_pages": settings.watched_max_pages,
        "film_limit": settings.watched_film_limit,
        "max_retries": settings.scrape_max_retries,
    }
    watchlist_kwargs = {
        "delay": settings.scrape_delay,
        "max_pages": settings.scrape_max_pages,
        "film_limit": settings.watchlist_film_limit,
        "max_retries": settings.scrape_max_retries,
    }

    def load(username, list_type, kwargs):
        return _load_user_films(
            username,
            list_type,
            settings=settings,
            enricher=enricher,
            pcache=pcache,
            scrape_kwargs=kwargs,
        )

    (watched1, _), (watched2, _), (watchlist1, _), (watchlist2, _) = (
        await asyncio.gather(
            load(first.username, "watched", watched_kwargs),
            load(second.username, "watched", watched_kwargs),
            load(first.username, "watchlist", watchlist_kwargs),
            load(second.username, "watchlist", watchlist_kwargs),
        )
    )
    if not watched1 or not watched2:
        raise ScrapeError("Blend için iki profilde de izlenen film verisi gerekli.")
    if enricher is not None:
        await asyncio.gather(
            enricher.ensure_details(_detail_sample(watched1, 40)),
            enricher.ensure_details(_detail_sample(watched2, 40)),
        )
    blend_result = _calculate_blend(watched1, watched2, top_n=20)
    common_watchlist = _common_watchlist_films(watchlist1, watchlist2)
    payload = {
        "username1": first.username,
        "username2": second.username,
        "score": blend_result["score"],
        "confidence": blend_result["confidence"],
        "watched_count1": len(watched1),
        "watched_count2": len(watched2),
        "common_count": blend_result["common_count"],
        "top_director": blend_result["top_director"],
        "top_director_count1": blend_result["top_director_count1"],
        "top_director_count2": blend_result["top_director_count2"],
        "films": [film.to_dict() for film in blend_result["films"]],
        "common_watchlist_films": [film.to_dict() for film in common_watchlist],
        "watchlist_public": bool(watchlist1) and bool(watchlist2),
        "watchlist_pending": False,
    }
    result_id = await asyncio.to_thread(
        service.save_blend_result,
        account,
        request_id,
        payload,
        algorithm_version=BLEND_VERSION,
    )
    return {
        **payload,
        "request_id": request_id,
        "result_id": result_id,
        "cached": False,
    }


_accepted_blend_flights: dict[str, asyncio.Task] = {}
_accepted_blend_lock = asyncio.Lock()


async def _accepted_blend_single_flight(
    account: Account, request_id: str, service: AuthService
) -> dict:
    async with _accepted_blend_lock:
        task = _accepted_blend_flights.get(request_id)
        if task is None:
            task = asyncio.create_task(
                _compute_accepted_blend(account, request_id, service)
            )
            _accepted_blend_flights[request_id] = task

            def clear(done_task, key=request_id):
                if _accepted_blend_flights.get(key) is done_task:
                    _accepted_blend_flights.pop(key, None)
                with contextlib.suppress(asyncio.CancelledError):
                    done_task.exception()

            task.add_done_callback(clear)
    return await asyncio.shield(task)


@app.post("/api/blends/requests/{request_id}/decision")
async def decide_blend_invite(
    request_id: str, req: BlendDecisionRequest, request: Request
) -> dict:
    _require_csrf(request)
    account = await _require_account(request)
    if req.decision == "accepted":
        await _enforce_heavy_rate_limit(request)
    service = _auth_service()
    try:
        decision = await asyncio.to_thread(
            service.decide_blend_request,
            account,
            request_id,
            req.decision,
            ip_hash=_ip_hash(request),
        )
        if decision.get("status") == "expired":
            return {"request_id": request_id, "status": "expired"}
        if req.decision == "rejected":
            return {"request_id": request_id, "status": "rejected"}
        async with _sem:
            result = await _accepted_blend_single_flight(
                account, request_id, service
            )
        return {"status": "accepted", "result": result}
    except BlendServiceError as exc:
        _raise_blend_http(exc)
    except ScrapeError as exc:
        _raise_scrape_http(exc)


@app.post("/api/blends/requests/{request_id}/result")
async def retry_blend_result(request_id: str, request: Request) -> dict:
    _require_csrf(request)
    await _enforce_heavy_rate_limit(request)
    account = await _require_account(request)
    service = _auth_service()
    try:
        async with _sem:
            result = await _accepted_blend_single_flight(
                account, request_id, service
            )
        return {"status": "accepted", "result": result}
    except BlendServiceError as exc:
        _raise_blend_http(exc)
    except ScrapeError as exc:
        _raise_scrape_http(exc)


@app.delete("/api/data")
async def delete_data(req: DeleteDataRequest, request: Request, response: Response) -> dict:
    """Delete a username's regenerable profile and recommendation caches."""
    await _enforce_delete_rate_limit(request)
    settings = get_settings()
    account = await _enforce_account_username(request, req.username)

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
    account_ok = True
    if settings.has_supabase:
        from supabase import create_client

        client = create_client(settings.supabase_url, settings.supabase_key)
        remote_cache = SupabaseCache(client)
        remote_ok = await asyncio.to_thread(
            _delete_cached_user_data, remote_cache, req.username
        )
        if getattr(settings, "has_auth", False) and account is not None and local_ok and remote_ok:
            try:
                await asyncio.to_thread(_auth_service().delete_account, account)
            except Exception:
                account_ok = False
        elif not getattr(settings, "has_auth", False):
            account_ok = await asyncio.to_thread(delete_user, client, req.username)

    if not (local_ok and remote_ok and account_ok):
        raise HTTPException(
            status_code=503,
            detail="Verinin tamamı silinemedi. Lütfen biraz sonra tekrar dene.",
        )
    log.warning("user data deleted username=%s", req.username)
    if getattr(settings, "has_auth", False):
        _clear_session_cookies(response)
    return {
        "ok": True,
        "username": req.username,
        "detail": "Kullanıcıya bağlı profil ve öneri cache'i silindi.",
    }


@app.post("/api/recommend")
async def recommend(req: RecommendRequest, request: Request):
    """SSE stream: queued? → scraping → enriching → ranking → llm → result."""
    global _q_waiting, _q_active
    account = await _enforce_account_username(request, req.username)
    await _enforce_heavy_rate_limit(request)
    try:
        suppressed_slugs = (
            await asyncio.to_thread(_auth_service().get_suppressed_slugs, account)
            if account is not None
            else set()
        )
    except RecommendationFeedbackError as exc:
        _raise_feedback_http(exc)

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
                watchlist_count = len(watchlist_films)
                watchlist_films = _filter_suppressed_films(
                    watchlist_films, suppressed_slugs
                )
                load_ms = round((time.perf_counter() - t1) * 1000)
                yield _sse({"type": "step", "step": "enriching"})
                log.warning("⏱ load films      %.2fs  (watched=%d[cache=%s], watchlist=%d[cache=%s])",
                            time.perf_counter() - t1, len(watched_films), w_cached,
                            len(watchlist_films), wl_cached)

                if not watchlist_films:
                    detail = (
                        "Tercihlerinden sonra önerilebilir film kalmadı. Öneri geçmişinden geri alabilirsin."
                        if watchlist_count
                        else "Watchlist boş veya gizli."
                    )
                    yield _sse({"type": "error", "detail": detail})
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
                        "watchlist_count": watchlist_count,
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
                    "watchlist_count": watchlist_count,
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
    account = await _enforce_account_username(request, req.username)
    await _enforce_heavy_rate_limit(request)
    try:
        suppressed_slugs = (
            await asyncio.to_thread(_auth_service().get_suppressed_slugs, account)
            if account is not None
            else set()
        )
    except RecommendationFeedbackError as exc:
        _raise_feedback_http(exc)

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
            watchlist_count = len(enriched)
            enriched = _filter_suppressed_films(enriched, suppressed_slugs)
            with_poster = [f for f in enriched if f.poster_url]
            pool = with_poster if len(with_poster) >= 3 else enriched
            if not pool:
                detail = (
                    "Tercihlerinden sonra önerilebilir film kalmadı. Öneri geçmişinden geri alabilirsin."
                    if watchlist_count
                    else "Watchlist boş veya gizli."
                )
                yield _sse({"type": "error", "detail": detail})
                return
            chosen = _random.sample(pool, min(3, len(pool)))
            log.warning("cache HIT  watchlist/%s (random pick)", req.username)
            yield _sse({
                "type": "result",
                "username": req.username,
                "watchlist_count": watchlist_count,
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

        watchlist_count = len(scraped_watchlist)
        scraped_watchlist = _filter_suppressed_films(
            scraped_watchlist, suppressed_slugs
        )
        if not scraped_watchlist:
            detail = (
                "Tercihlerinden sonra önerilebilir film kalmadı. Öneri geçmişinden geri alabilirsin."
                if watchlist_count
                else "Watchlist boş veya gizli."
            )
            yield _sse({"type": "error", "detail": detail})
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
            "watchlist_count": watchlist_count,
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
    await _enforce_account_username(request, req.username1)
    if getattr(get_settings(), "has_auth", False):
        raise HTTPException(
            status_code=409,
            detail="Blend için karşı taraf onayı gerekir. Inbox akışı P1 ile açılacak.",
        )
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
