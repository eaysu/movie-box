#!/usr/bin/env python3
"""Cache warmer — bloklanmayan bir makineden (lokal) çalıştırılır.

Render'ın datacenter IP'si Cloudflare tarafından bloklandığından, kullanıcı
profillerini buradan (residential IP) çekip Supabase'e yazarız. Render sonra
scrape yapmadan doğrudan cache'ten okur (cache HIT → ~5s, dış scraping servisi yok).

Kullanım:
    python -m scripts.warm_cache                      # varsayılan kullanıcı listesi
    python -m scripts.warm_cache enesaysu honeypiie3  # belirli kullanıcılar

Notlar:
  • .env.local içindeki SUPABASE_URL/KEY ve TMDB_API_KEY kullanılır.
  • Letterboxd doğrudan okunur; proxy veya ücretli scraping servisi kullanılmaz.
  • Her kullanıcı için watched + watchlist taze çekilip üzerine yazılır (force).
  • TTL 24 saat — günde bir kez çalıştırmak yeterli (cron'a bağlanabilir).
"""

import asyncio
import sys
import time

from app.config import get_settings
from app.enrich import Enricher
from app.main import _make_cache, _make_persistent_cache, _load_user_films
from app.scraper import ScrapeError

# Önceden ısıtılacak varsayılan kullanıcılar.
DEFAULT_USERS = [
    "enesaysu",
    "honeypiie3",
    "prodigytsu",
    "kelebekis",
    "sedayilmazz",
    "melikezcc",
]


async def warm_user(username: str, *, settings, enricher, pcache) -> None:
    """Bir kullanıcının watched + watchlist profilini çekip cache'e yazar."""
    watched_kwargs = dict(
        delay=settings.scrape_delay, max_pages=settings.watched_max_pages,
        film_limit=settings.watched_film_limit, max_retries=settings.scrape_max_retries,
    )
    watchlist_kwargs = dict(
        delay=settings.scrape_delay, max_pages=settings.scrape_max_pages,
        film_limit=settings.watchlist_film_limit, max_retries=settings.scrape_max_retries,
    )

    t = time.perf_counter()
    try:
        (watched, _wc), (watchlist, _lc) = await asyncio.gather(
            _load_user_films(username, "watched", settings=settings,
                             enricher=enricher, pcache=pcache,
                             scrape_kwargs=watched_kwargs, force=True),
            _load_user_films(username, "watchlist", settings=settings,
                             enricher=enricher, pcache=pcache,
                             scrape_kwargs=watchlist_kwargs, force=True),
        )
    except ScrapeError as exc:
        print(f"  ✗ @{username}: {exc}")
        return

    dt = time.perf_counter() - t
    print(f"  ✓ @{username}: watched={len(watched)} watchlist={len(watchlist)}  ({dt:.1f}s)")


async def main(users: list[str]) -> None:
    settings = get_settings()
    if not settings.has_supabase:
        print("HATA: Supabase yapılandırılmamış (.env.local SUPABASE_URL/KEY). Cache yazılamaz.")
        sys.exit(1)

    client, cache = _make_cache(settings)
    pcache = _make_persistent_cache(settings, client)
    enricher = Enricher(settings.tmdb_api_key, cache) if settings.has_tmdb else None

    print(f"Cache warming → Supabase ({len(users)} kullanıcı, TTL 24s)")
    print(f"  TMDb: {'açık' if settings.has_tmdb else 'KAPALI'} | "
          f"film_limit watched={settings.watched_film_limit} watchlist={settings.watchlist_film_limit}\n")

    t0 = time.perf_counter()
    # Sıralı çalıştır — paralel scrape Cloudflare'i tetikleyebilir, acelemiz yok.
    for u in users:
        await warm_user(u, settings=settings, enricher=enricher, pcache=pcache)

    print(f"\nBitti — {len(users)} kullanıcı, toplam {time.perf_counter() - t0:.1f}s")


if __name__ == "__main__":
    arg_users = sys.argv[1:] or DEFAULT_USERS
    asyncio.run(main(arg_users))
