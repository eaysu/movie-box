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
import logging
import os
import time
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel

from .config import get_settings
from .cache import Cache
from .database import SupabaseCache, upsert_user
from .enrich import Enricher, EnrichedFilm
from .llm import rank_candidates
from .recommender import rank_watchlist
from .scraper import ScrapeError, scrape_watchlist, scrape_watched

app = FastAPI(title="Letterboxd AI Recommender", version="0.2.0")
log = logging.getLogger("moviebox")

_allowed_origins = os.environ.get("ALLOWED_ORIGINS", "*").split(",")
app.add_middleware(
    CORSMiddleware,
    allow_origins=_allowed_origins,
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type"],
)

STATIC_DIR = Path(__file__).resolve().parent.parent / "static"


def _make_cache(settings):
    # TMDb cache her zaman SQLite — Supabase senkron HTTP yaptığı için
    # her film başına ~80ms ekler (300 film = ~24s kayıp).
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


@app.get("/api/health")
def health() -> dict:
    settings = get_settings()
    return {
        "status": "ok",
        "tmdb_enabled": settings.has_tmdb,
        "llm_enabled": settings.has_openai,
        "supabase_enabled": settings.has_supabase,
    }


@app.post("/api/recommend")
async def recommend(req: RecommendRequest) -> dict:
    """Tam pipeline: watched → watchlist → TMDb → benzerlik → LLM."""
    t0 = time.perf_counter()
    settings = get_settings()

    # 1. Scraping (parallel — farklı endpoint'ler, Letterboxd'u rahatsız etmez)
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
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    log.warning("⏱ scraping       %.2fs  (watched=%d, watchlist=%d)",
                time.perf_counter() - t1, len(scraped_watched), len(scraped_watchlist))

    if not scraped_watchlist:
        raise HTTPException(status_code=404, detail="Watchlist boş veya gizli.")

    # Supabase'e kullanıcıyı kaydet (opsiyonel).
    supabase_client, cache = _make_cache(settings)
    if supabase_client is not None:
        upsert_user(supabase_client, req.username)

    # 2. TMDb enrichment (parallel)
    t2 = time.perf_counter()
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
    log.warning("⏱ tmdb enrich     %.2fs  (watched=%d, watchlist=%d, sqlite_hits=%s)",
                time.perf_counter() - t2,
                len(watched_films), len(watchlist_films), cache_hits)

    # 3. TF-IDF ranking
    t3 = time.perf_counter()
    candidate_count = settings.num_recommendations * 2
    candidates = rank_watchlist(watched_films, watchlist_films, n=candidate_count)
    log.warning("⏱ tfidf rank      %.2fs  (candidates=%d)", time.perf_counter() - t3, len(candidates))

    # 4. LLM reranking
    t4 = time.perf_counter()
    result = await rank_candidates(settings, watched_films, candidates)
    log.warning("⏱ llm rerank      %.2fs  (llm_used=%s)", time.perf_counter() - t4, result.get("llm_used"))

    log.warning("⏱ TOTAL           %.2fs", time.perf_counter() - t0)

    return {
        "username": req.username,
        "watched_count": len(watched_films),
        "watchlist_count": len(watchlist_films),
        "matched_on_tmdb": sum(1 for f in watchlist_films if f.matched),
        "taste_summary": result["taste_summary"],
        "recommendations": result["recommendations"],
        "meta": {
            "tmdb_enabled": settings.has_tmdb,
            "llm_used": result.get("llm_used", False),
        },
    }
