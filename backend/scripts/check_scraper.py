#!/usr/bin/env python3
"""Direct Letterboxd scraper canary; no proxy or paid service is used.

Usage:
    python -m scripts.check_scraper <letterboxd_username>

Exit code 0 means the public watchlist returned parseable films. This command is
intended for a low-frequency (for example daily) monitor, not a frequent uptime
probe.
"""

import argparse
import asyncio
import json
import time

from app.scraper import ScrapeError, scrape_watchlist


async def check(username: str) -> int:
    started = time.perf_counter()
    try:
        films, complete = await scrape_watchlist(
            username,
            delay=0,
            max_pages=1,
            film_limit=28,
            max_retries=2,
        )
    except ScrapeError as exc:
        print(json.dumps({
            "ok": False,
            "username": username,
            "error_code": exc.code,
            "error": str(exc),
        }))
        return 1

    payload = {
        "ok": bool(films and complete),
        "username": username,
        "film_count": len(films),
        "complete": complete,
        "duration_ms": round((time.perf_counter() - started) * 1000),
        "sample_slug": films[0].slug if films else None,
    }
    print(json.dumps(payload, ensure_ascii=False))
    return 0 if payload["ok"] else 1


def main() -> int:
    parser = argparse.ArgumentParser(description="Check current Letterboxd parser health")
    parser.add_argument("username", help="Public Letterboxd username with a non-empty watchlist")
    args = parser.parse_args()
    return asyncio.run(check(args.username.strip().lstrip("@").lower()))


if __name__ == "__main__":
    raise SystemExit(main())
