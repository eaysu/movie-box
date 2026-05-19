"""FastAPI app — yeni mimari.

Akış:
  1. İzlenen filmler scrape edilir  (/films/)   → zevk profili kaynağı
  2. Watchlist scrape edilir         (/watchlist/) → aday havuzu
  3. Her iki liste TMDb ile zenginleştirilir
  4. Watchlist filmleri zevk profiline cosine benzerliğine göre sıralanır
  5. LLM en iyi N filmi seçer ve Türkçe gerekçe yazar

Çalıştırmak için:
  uvicorn app.main:app --reload --port 8001
"""

import asyncio
import os
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

_allowed_origins = os.environ.get("ALLOWED_ORIGINS", "*").split(",")
app.add_middleware(
    CORSMiddleware,
    allow_origins=_allowed_origins,
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type"],
)

STATIC_DIR = Path(__file__).resolve().parent.parent / "static"


def _make_cache(settings):
    if settings.has_supabase:
        from supabase import create_client
        client = create_client(settings.supabase_url, settings.supabase_key)
        return client, SupabaseCache(client)
    return None, Cache(settings.cache_db_path)


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
    settings = get_settings()

    # 1. İzlenen filmler (zevk profili) ve watchlist'i sırayla çek.
    #    Aynı anda iki scraper açmak Letterboxd'u rahatsız edebilir.
    try:
        scraped_watched = await scrape_watched(
            req.username,
            delay=settings.scrape_delay,
            max_pages=settings.watched_max_pages,
        )
        scraped_watchlist = await scrape_watchlist(
            req.username,
            delay=settings.scrape_delay,
            max_pages=settings.scrape_max_pages,
        )
    except ScrapeError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    if not scraped_watchlist:
        raise HTTPException(
            status_code=404,
            detail="Watchlist boş veya gizli.",
        )

    # Supabase'e kullanıcıyı kaydet (opsiyonel).
    supabase_client, cache = _make_cache(settings)
    if supabase_client is not None:
        upsert_user(supabase_client, req.username)

    # 2. TMDb ile zenginleştir.
    if settings.has_tmdb:
        enricher = Enricher(settings.tmdb_api_key, cache)
        # İki listeyi eş zamanlı zenginleştir (farklı API, Letterboxd değil).
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

    # 3. Watchlist'i izleme geçmişine benzerliğe göre sırala.
    #    Aday havuzu boyutu = num_recommendations × 3 (LLM seçim payı için).
    candidate_count = settings.num_recommendations * 3
    candidates = rank_watchlist(watched_films, watchlist_films, n=candidate_count)

    # 4. LLM en iyi N'i seçer ve gerekçelendirir.
    result = await rank_candidates(settings, watched_films, candidates)

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
