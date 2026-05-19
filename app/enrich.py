"""Layer 2 — enrich scraped films with TMDb metadata.

Scraping gives us only titles and slugs. To recommend well we need overviews,
genres, directors and keywords. TMDb has a real, free API for exactly this.
Results are cached so a film looked up once is never fetched again.
"""

import asyncio
from dataclasses import dataclass, field, asdict
from typing import Optional

import httpx

from .cache import Cache

TMDB_BASE = "https://api.themoviedb.org/3"
TMDB_IMAGE_BASE = "https://image.tmdb.org/t/p/w500"
SEARCH_TTL = 60 * 60 * 24 * 30  # 30 days


@dataclass
class EnrichedFilm:
    title: str
    year: Optional[int] = None
    slug: str = ""
    tmdb_id: Optional[int] = None
    overview: str = ""
    genres: list[str] = field(default_factory=list)
    director: str = ""
    keywords: list[str] = field(default_factory=list)
    vote_average: float = 0.0
    poster_url: Optional[str] = None
    matched: bool = False  # True once TMDb data was found
    similarity: float = 0.0
    reason: str = ""

    def to_dict(self) -> dict:
        d = asdict(self)
        d["text_blob"] = self.text_blob
        return d

    @property
    def text_blob(self) -> str:
        """Everything an embedding model should 'read' about this film."""
        parts = [
            self.title,
            f"Directed by {self.director}." if self.director else "",
            f"Genres: {', '.join(self.genres)}." if self.genres else "",
            self.overview,
            f"Themes: {', '.join(self.keywords)}." if self.keywords else "",
        ]
        return " ".join(p for p in parts if p).strip()


class Enricher:
    """Wraps the TMDb API with caching and best-match selection."""

    def __init__(self, api_key: str, cache: Cache):
        self.api_key = api_key
        self.cache = cache
        self._genre_map: dict[int, str] = {}

    async def _get(self, client: httpx.AsyncClient, path: str, **params) -> dict:
        params["api_key"] = self.api_key
        resp = await client.get(f"{TMDB_BASE}{path}", params=params)
        resp.raise_for_status()
        return resp.json()

    async def _load_genre_map(self, client: httpx.AsyncClient) -> None:
        cached = self.cache.get("tmdb", "genre_map")
        if cached:
            self._genre_map = {int(k): v for k, v in cached.items()}
            return
        data = await self._get(client, "/genre/movie/list")
        self._genre_map = {g["id"]: g["name"] for g in data.get("genres", [])}
        self.cache.set("tmdb", "genre_map", self._genre_map)

    @staticmethod
    def _score_match(result: dict, title: str, year: Optional[int]) -> float:
        """Rough relevance score for picking the right search hit."""
        score = float(result.get("popularity", 0.0))
        if result.get("title", "").lower() == title.lower():
            score += 1000.0
        rel = result.get("release_date", "")
        if year and rel[:4].isdigit():
            if int(rel[:4]) == year:
                score += 500.0
            elif abs(int(rel[:4]) - year) <= 1:
                score += 100.0
        return score

    async def _enrich_one(
        self, client: httpx.AsyncClient, title: str, year: Optional[int], slug: str
    ) -> EnrichedFilm:
        cache_key = slug or f"{title}:{year}"
        cached = self.cache.get("tmdb", cache_key, ttl=SEARCH_TTL)
        if cached:
            return EnrichedFilm(**cached)

        film = EnrichedFilm(title=title, year=year, slug=slug)

        try:
            search = await self._get(
                client, "/search/movie", query=title, **({"year": year} if year else {})
            )
            results = search.get("results", [])
            if not results:
                self.cache.set("tmdb", cache_key, film.to_dict())
                return film

            best = max(results, key=lambda r: self._score_match(r, title, year))
            film.tmdb_id = best.get("id")
            film.overview = best.get("overview", "") or ""
            film.vote_average = float(best.get("vote_average", 0.0) or 0.0)
            film.genres = [
                self._genre_map.get(gid, "")
                for gid in best.get("genre_ids", [])
                if gid in self._genre_map
            ]
            rel = best.get("release_date", "")
            if rel[:4].isdigit() and not film.year:
                film.year = int(rel[:4])
            poster_path = best.get("poster_path", "")
            if poster_path:
                film.poster_url = f"{TMDB_IMAGE_BASE}{poster_path}"

            # A second call gets keywords + director.
            if film.tmdb_id:
                details = await self._get(
                    client,
                    f"/movie/{film.tmdb_id}",
                    append_to_response="keywords,credits",
                )
                film.keywords = [
                    k["name"] for k in details.get("keywords", {}).get("keywords", [])
                ][:12]
                for crew in details.get("credits", {}).get("crew", []):
                    if crew.get("job") == "Director":
                        film.director = crew.get("name", "")
                        break

            film.matched = True
        except httpx.HTTPError:
            # Leave the film unmatched; the pipeline still runs on its title.
            pass

        self.cache.set("tmdb", cache_key, film.to_dict())
        return film

    async def enrich(self, films: list) -> list[EnrichedFilm]:
        """Enrich a list of films (dicts or ScrapedFilm objects)."""
        async with httpx.AsyncClient(timeout=20.0) as client:
            await self._load_genre_map(client)

            sem = asyncio.Semaphore(8)  # be gentle on the API

            async def worker(f) -> EnrichedFilm:
                title = f["title"] if isinstance(f, dict) else f.title
                year = f.get("year") if isinstance(f, dict) else f.year
                slug = (f.get("slug", "") if isinstance(f, dict) else f.slug) or ""
                scraped_poster = (
                    f.get("poster_url") if isinstance(f, dict) else getattr(f, "poster_url", None)
                )
                async with sem:
                    enriched = await self._enrich_one(client, title, year, slug)
                    # Fall back to the Letterboxd-scraped poster if TMDb has none.
                    if not enriched.poster_url and scraped_poster:
                        enriched.poster_url = scraped_poster
                    return enriched

            return await asyncio.gather(*(worker(f) for f in films))
