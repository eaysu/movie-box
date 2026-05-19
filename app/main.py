"""FastAPI app — wires the five layers into one endpoint.

Run with:  uvicorn app.main:app --reload
"""

from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel

from .config import get_settings
from .cache import Cache
from .database import SupabaseCache, upsert_user
from .enrich import Enricher, EnrichedFilm
from .llm import rank_candidates
from .recommender import CatalogNotBuilt, Recommender
from .scraper import ScrapeError, scrape_watchlist

app = FastAPI(title="Letterboxd AI Recommender", version="0.1.0")

STATIC_DIR = Path(__file__).resolve().parent.parent / "static"

_recommender: Recommender | None = None


def get_recommender() -> Recommender:
    global _recommender
    if _recommender is None:
        try:
            _recommender = Recommender(get_settings())
        except CatalogNotBuilt as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
    return _recommender


def _make_cache(settings):
    """Return (supabase_client, cache). Falls back to SQLite when no Supabase key."""
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
    catalog_size = 0
    catalog_ready = False
    try:
        catalog_size = get_recommender().size
        catalog_ready = True
    except HTTPException:
        pass
    return {
        "status": "ok",
        "tmdb_enabled": settings.has_tmdb,
        "llm_enabled": settings.has_openai,
        "supabase_enabled": settings.has_supabase,
        "embedding_provider": settings.embedding_provider,
        "catalog_ready": catalog_ready,
        "catalog_size": catalog_size,
    }


@app.get("/api/watchlist/{username}")
async def watchlist(username: str) -> dict:
    settings = get_settings()
    try:
        films = await scrape_watchlist(
            username, delay=settings.scrape_delay, max_pages=settings.scrape_max_pages
        )
    except ScrapeError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"username": username, "count": len(films), "films": [f.to_dict() for f in films]}


@app.post("/api/recommend")
async def recommend(req: RecommendRequest) -> dict:
    """The full pipeline: scrape → enrich → embed → match → LLM rank."""
    settings = get_settings()
    recommender = get_recommender()

    # 1. Scrape the watchlist.
    try:
        scraped = await scrape_watchlist(
            req.username, delay=settings.scrape_delay, max_pages=settings.scrape_max_pages
        )
    except ScrapeError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    if not scraped:
        raise HTTPException(status_code=404, detail="Watchlist is empty or private.")

    # Resolve cache backend + track user in Supabase.
    supabase_client, cache = _make_cache(settings)
    if supabase_client is not None:
        upsert_user(supabase_client, req.username)

    # 2. Enrich with TMDb.
    if settings.has_tmdb:
        enricher = Enricher(settings.tmdb_api_key, cache)
        watchlist_films = await enricher.enrich(scraped)
    else:
        watchlist_films = [
            EnrichedFilm(title=f.title, year=f.year, slug=f.slug, poster_url=f.poster_url)
            for f in scraped
        ]

    # 3 + 4. Embed and find nearest catalog films.
    try:
        candidates = recommender.recommend(watchlist_films, settings.candidate_pool_size)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    # 5. LLM curation.
    result = await rank_candidates(settings, watchlist_films, candidates)

    return {
        "username": req.username,
        "watchlist_count": len(watchlist_films),
        "matched_on_tmdb": sum(1 for f in watchlist_films if f.matched),
        "taste_summary": result["taste_summary"],
        "recommendations": result["recommendations"],
        "meta": {
            "tmdb_enabled": settings.has_tmdb,
            "llm_used": result.get("llm_used", False),
            "embedding_provider": settings.embedding_provider,
            "candidate_pool_size": len(candidates),
        },
    }
