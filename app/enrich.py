"""Layer 2 — enrich scraped films with TMDb metadata.

Scraping gives us only titles and slugs. To recommend well we need overviews,
genres, directors and keywords. TMDb has a real, free API for exactly this.
Results are cached so a film looked up once is never fetched again.
"""

import asyncio
import logging
from dataclasses import dataclass, field, asdict
from typing import Optional

import httpx

from .cache import Cache

TMDB_BASE = "https://api.themoviedb.org/3"
TMDB_IMAGE_BASE = "https://image.tmdb.org/t/p/w500"
SEARCH_TTL = 60 * 60 * 24 * 30  # 30 days
log = logging.getLogger("moviebox")

_tmdb_client: Optional[httpx.AsyncClient] = None
_tmdb_client_lock = asyncio.Lock()
_tmdb_request_sem = asyncio.Semaphore(16)


async def _get_tmdb_client() -> httpx.AsyncClient:
    """Return the process-wide pooled TMDb client."""
    global _tmdb_client
    async with _tmdb_client_lock:
        if _tmdb_client is None or _tmdb_client.is_closed:
            _tmdb_client = httpx.AsyncClient(
                timeout=httpx.Timeout(20.0),
                limits=httpx.Limits(max_connections=20, max_keepalive_connections=16),
            )
        return _tmdb_client


async def close_tmdb_client() -> None:
    """Close the shared connection pool during application shutdown."""
    global _tmdb_client
    if _tmdb_client is not None and not _tmdb_client.is_closed:
        await _tmdb_client.aclose()
    _tmdb_client = None


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
    details_loaded: bool = False  # director/keywords detail call completed
    similarity: float = 0.0
    reason: str = ""
    user_rating: Optional[float] = None  # Letterboxd kullanıcı puanı (0.5-5.0)

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
        self._genre_lock = asyncio.Lock()
        self._cache_hits = 0
        self._api_calls = 0
        self._rate_limits = 0
        self._l2_hydrated = 0
        self._l2_flushed = 0

    async def _prefetch_cache(
        self, keys: list[str], ttl: Optional[float] = None
    ) -> None:
        """Batch-hydrate the local cache when the backend supports an L2."""
        prefetch = getattr(self.cache, "prefetch", None)
        if prefetch and keys:
            self._l2_hydrated += await asyncio.to_thread(
                prefetch, "tmdb", keys, ttl
            )

    async def _flush_cache(self) -> None:
        """Persist queued local mutations without blocking the event loop."""
        flush = getattr(self.cache, "flush", None)
        if flush:
            self._l2_flushed += await asyncio.to_thread(flush)

    async def _get(self, client: httpx.AsyncClient, path: str, **params) -> dict:
        params["api_key"] = self.api_key
        for attempt in range(3):
            async with _tmdb_request_sem:
                resp = await client.get(f"{TMDB_BASE}{path}", params=params)
                self._api_calls += 1

            if resp.status_code == 429:
                self._rate_limits += 1
                retry_after = resp.headers.get("Retry-After", "")
                try:
                    delay = max(0.0, min(float(retry_after), 10.0))
                except ValueError:
                    delay = 0.5 * (2 ** attempt)
                log.warning("tmdb 429 path=%s retry=%d delay=%.2fs", path, attempt + 1, delay)
                if attempt < 2:
                    await asyncio.sleep(delay)
                    continue

            if resp.status_code >= 500 and attempt < 2:
                await asyncio.sleep(0.5 * (2 ** attempt))
                continue

            resp.raise_for_status()
            return resp.json()

        raise RuntimeError("TMDb retry loop exhausted")

    async def _load_genre_map(self, client: httpx.AsyncClient) -> None:
        if self._genre_map:
            return
        async with self._genre_lock:
            if self._genre_map:
                return
            cached = await asyncio.to_thread(self.cache.get, "tmdb", "genre_map")
            if cached:
                self._genre_map = {int(k): v for k, v in cached.items()}
                return
            data = await self._get(client, "/genre/movie/list")
            self._genre_map = {g["id"]: g["name"] for g in data.get("genres", [])}
            await asyncio.to_thread(self.cache.set, "tmdb", "genre_map", self._genre_map)

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

    async def _load_details(
        self, client: httpx.AsyncClient, film: EnrichedFilm, cache_key: str
    ) -> EnrichedFilm:
        if not film.tmdb_id or film.details_loaded:
            return film
        try:
            details = await self._get(
                client,
                f"/movie/{film.tmdb_id}",
                append_to_response="keywords,credits",
            )
        except httpx.HTTPError:
            return film

        film.keywords = [
            k["name"] for k in details.get("keywords", {}).get("keywords", [])
        ][:12]
        for crew in details.get("credits", {}).get("crew", []):
            if crew.get("job") == "Director":
                film.director = crew.get("name", "")
                break
        film.details_loaded = True
        await asyncio.to_thread(self.cache.set, "tmdb", cache_key, film.to_dict())
        return film

    async def _enrich_one(
        self,
        client: httpx.AsyncClient,
        title: str,
        year: Optional[int],
        slug: str,
        *,
        include_details: bool,
    ) -> EnrichedFilm:
        cache_key = slug or f"{title}:{year}"
        cached = await asyncio.to_thread(
            self.cache.get, "tmdb", cache_key, ttl=SEARCH_TTL
        )
        if cached:
            cached.pop("text_blob", None)
            cached.pop("similarity", None)
            cached.pop("reason", None)
            if "details_loaded" not in cached:
                cached["details_loaded"] = bool(
                    cached.get("director") or cached.get("keywords")
                )
            self._cache_hits = getattr(self, "_cache_hits", 0) + 1
            film = EnrichedFilm(**cached)
            if include_details and not film.details_loaded:
                return await self._load_details(client, film, cache_key)
            return film

        film = EnrichedFilm(title=title, year=year, slug=slug)

        try:
            search = await self._get(
                client, "/search/movie", query=title, **({"year": year} if year else {})
            )
            results = search.get("results", [])
            if not results:
                await asyncio.to_thread(self.cache.set, "tmdb", cache_key, film.to_dict())
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
            backdrop_path = best.get("backdrop_path", "")
            if poster_path:
                film.poster_url = f"{TMDB_IMAGE_BASE}{poster_path}"
            elif backdrop_path:
                # Backdrop fallback: portrait poster yoksa landscape backdrop kullan.
                # Frontend card'ları object-fit: cover ile bu durumu handle eder.
                film.poster_url = f"https://image.tmdb.org/t/p/w780{backdrop_path}"

            film.matched = True
            if include_details:
                await self._load_details(client, film, cache_key)
        except httpx.HTTPError:
            # HTTP hatası (rate limit, timeout): cache'e yazma — bir sonraki istekte tekrar denensin.
            return film

        await asyncio.to_thread(self.cache.set, "tmdb", cache_key, film.to_dict())
        return film

    async def enrich(self, films: list, *, include_details: bool = True) -> list[EnrichedFilm]:
        """Search-enrich films; optionally fetch director/keyword details."""
        client = await _get_tmdb_client()
        cache_keys = [
            (f.get("slug", "") or f"{f['title']}:{f.get('year')}")
            if isinstance(f, dict)
            else (f.slug or f"{f.title}:{f.year}")
            for f in films
        ]
        await self._prefetch_cache(["genre_map"])
        await self._prefetch_cache(cache_keys, SEARCH_TTL)
        await self._load_genre_map(client)

        async def worker(f) -> EnrichedFilm:
            title = f["title"] if isinstance(f, dict) else f.title
            year = f.get("year") if isinstance(f, dict) else f.year
            slug = (f.get("slug", "") if isinstance(f, dict) else f.slug) or ""
            scraped_poster = (
                f.get("poster_url") if isinstance(f, dict) else getattr(f, "poster_url", None)
            )
            user_rating = (
                f.get("user_rating") if isinstance(f, dict) else getattr(f, "user_rating", None)
            )
            enriched = await self._enrich_one(
                client, title, year, slug, include_details=include_details
            )
            if not enriched.poster_url and scraped_poster:
                enriched.poster_url = scraped_poster
            # user_rating TMDb cache'ine girmemeli (kişiye özel).
            enriched.user_rating = user_rating
            return enriched

        try:
            result = await asyncio.gather(*(worker(f) for f in films))
        finally:
            await self._flush_cache()
        log.warning(
            "tmdb enrich films=%d details=%s cache_hits=%d api_calls=%d "
            "rate_limits=%d l2_hydrated=%d l2_flushed=%d",
            len(films),
            include_details,
            self._cache_hits,
            self._api_calls,
            self._rate_limits,
            self._l2_hydrated,
            self._l2_flushed,
        )
        return result

    async def ensure_details(self, films: list[EnrichedFilm]) -> list[EnrichedFilm]:
        """Fetch director/keywords only for the selected, already searched films."""
        if not films:
            return films
        client = await _get_tmdb_client()
        cache_keys = [
            film.slug or f"{film.title}:{film.year}"
            for film in films
            if film.tmdb_id and not film.details_loaded
        ]
        await self._prefetch_cache(cache_keys, SEARCH_TTL)

        async def worker(film: EnrichedFilm) -> EnrichedFilm:
            if film.details_loaded or not film.tmdb_id:
                return film
            cache_key = film.slug or f"{film.title}:{film.year}"
            cached = await asyncio.to_thread(
                self.cache.get, "tmdb", cache_key, ttl=SEARCH_TTL
            )
            if cached and cached.get("details_loaded"):
                film.director = cached.get("director", "")
                film.keywords = cached.get("keywords", [])
                film.details_loaded = True
                self._cache_hits += 1
                return film
            return await self._load_details(client, film, cache_key)

        before_calls = self._api_calls
        try:
            result = await asyncio.gather(*(worker(film) for film in films))
        finally:
            await self._flush_cache()
        log.warning(
            "tmdb details films=%d api_calls=%d",
            len(films),
            self._api_calls - before_calls,
        )
        return result

    async def person_photos(self, names: list[str]) -> dict[str, str]:
        """Map a director name → a portrait URL via TMDb person search (cached)."""
        wanted = [n.strip() for n in names if n and n.strip()]
        if not wanted:
            return {}
        client = await _get_tmdb_client()
        keys = [f"person:{n.lower()}" for n in wanted]
        await self._prefetch_cache(keys, SEARCH_TTL)
        out: dict[str, str] = {}

        async def worker(name: str) -> None:
            key = f"person:{name.lower()}"
            cached = await asyncio.to_thread(self.cache.get, "tmdb", key, ttl=SEARCH_TTL)
            if cached is not None:
                self._cache_hits += 1
                if cached.get("photo_url"):
                    out[name] = cached["photo_url"]
                return
            photo = ""
            try:
                data = await self._get(client, "/search/person", query=name)
                results = data.get("results", []) or []
                best = max(
                    results,
                    key=lambda r: (
                        1000.0 if r.get("name", "").lower() == name.lower() else 0.0
                    )
                    + float(r.get("popularity", 0.0) or 0.0),
                    default=None,
                )
                if best and best.get("profile_path"):
                    photo = f"https://image.tmdb.org/t/p/w185{best['profile_path']}"
            except httpx.HTTPError:
                return  # transient — don't cache, retry next time
            await asyncio.to_thread(
                self.cache.set, "tmdb", key, {"photo_url": photo}
            )
            if photo:
                out[name] = photo

        try:
            await asyncio.gather(*(worker(n) for n in wanted))
        finally:
            await self._flush_cache()
        return out
