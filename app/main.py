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
import time
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
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
