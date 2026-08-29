#!/usr/bin/env python3
"""Run the real username pipeline with an isolated, disposable local cache.

This diagnostic reads public Letterboxd pages and TMDb metadata directly. It
does not call OpenAI and never reads from or writes to Supabase.

Usage:
    python -m scripts.check_profiles username [username ...]
"""

import argparse
import asyncio
import json
import tempfile
import time
from pathlib import Path

from app.cache import Cache
from app.config import get_settings
from app.enrich import Enricher, close_tmdb_client
from app.main import _detail_sample, _load_user_films
from app.recommender import rank_watchlist
from app.scraper import ScrapeError


async def _check_user(username: str, *, settings, enricher, cache) -> dict:
    started = time.perf_counter()
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
    before_api = getattr(enricher, "_api_calls", 0)
    before_hits = getattr(enricher, "_cache_hits", 0)

    try:
        (watched, _), (watchlist, _) = await asyncio.gather(
            _load_user_films(
                username,
                "watched",
                settings=settings,
                enricher=enricher,
                pcache=cache,
                scrape_kwargs=watched_kwargs,
                force=True,
            ),
            _load_user_films(
                username,
                "watchlist",
                settings=settings,
                enricher=enricher,
                pcache=cache,
                scrape_kwargs=watchlist_kwargs,
                force=True,
            ),
        )
        if enricher is not None:
            await enricher.ensure_details(_detail_sample(watched, 24))
        candidates = rank_watchlist(watched, watchlist, n=10)
        if enricher is not None:
            await enricher.ensure_details(candidates)
    except ScrapeError as exc:
        return {
            "ok": False,
            "username": username,
            "error_code": exc.code,
            "error": str(exc),
            "duration_ms": round((time.perf_counter() - started) * 1000),
        }

    return {
        "ok": bool(watched and watchlist),
        "username": username,
        "watched_count": len(watched),
        "watchlist_count": len(watchlist),
        "rated_count": sum(film.user_rating is not None for film in watched),
        "recommendations": [film.slug or film.title for film in candidates[:5]],
        "tmdb_api_calls": getattr(enricher, "_api_calls", 0) - before_api,
        "tmdb_cache_hits": getattr(enricher, "_cache_hits", 0) - before_hits,
        "duration_ms": round((time.perf_counter() - started) * 1000),
        "llm_tested": False,
        "persistent_write": False,
    }


async def check_profiles(usernames: list[str]) -> int:
    settings = get_settings()
    results = []
    try:
        with tempfile.TemporaryDirectory(prefix="moviebox-profile-check-") as tmp:
            cache = Cache(Path(tmp) / "cache.sqlite3")
            enricher = Enricher(settings.tmdb_api_key, cache) if settings.has_tmdb else None
            for username in usernames:
                result = await _check_user(
                    username, settings=settings, enricher=enricher, cache=cache
                )
                results.append(result)
                print(json.dumps(result, ensure_ascii=False), flush=True)
    finally:
        await close_tmdb_client()
    return 0 if all(result["ok"] for result in results) else 1


def main() -> int:
    parser = argparse.ArgumentParser(description="Check real Movieboxd profiles locally")
    parser.add_argument("usernames", nargs="+")
    args = parser.parse_args()
    usernames = [username.strip().lstrip("@").lower() for username in args.usernames]
    return asyncio.run(check_profiles(usernames))


if __name__ == "__main__":
    raise SystemExit(main())
