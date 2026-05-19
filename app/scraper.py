"""Layer 1 — scrape Letterboxd film lists (watchlist and watched films).

Letterboxd has no public API, so we fetch HTML and parse the poster grid.
The CSS selectors are best-effort; Letterboxd can change its markup at any time.
"""

import asyncio
import re
from dataclasses import dataclass, asdict
from typing import Optional

import httpx
from bs4 import BeautifulSoup

BASE_URL = "https://letterboxd.com"
USER_AGENT = (
    "Mozilla/5.0 (compatible; LetterboxdRecommender/0.1; "
    "personal project; +https://github.com/eaysu/movie-box)"
)


class ScrapeError(Exception):
    """Raised when a Letterboxd page cannot be retrieved."""


@dataclass
class ScrapedFilm:
    title: str
    year: Optional[int]
    slug: str
    poster_url: Optional[str] = None

    def to_dict(self) -> dict:
        return asdict(self)


def _slug_to_title(slug: str) -> str:
    return slug.replace("-", " ").strip().title()


def _parse_year_from_name(name: str) -> tuple[str, Optional[int]]:
    m = re.search(r"^(.*?)\s*\((\d{4})\)\s*$", name.strip())
    if m:
        return m.group(1).strip(), int(m.group(2))
    return name.strip(), None


def _parse_page(html: str) -> list[ScrapedFilm]:
    soup = BeautifulSoup(html, "lxml")
    films: list[ScrapedFilm] = []

    # Current markup (2024+): LazyPoster with data-item-slug
    lazy_posters = soup.select("div[data-item-slug]")
    if lazy_posters:
        for div in lazy_posters:
            slug = div.get("data-item-slug", "").strip()
            if not slug:
                continue
            display_name = (
                div.get("data-item-full-display-name", "")
                or div.get("data-item-name", "")
            ).strip()
            title, year = (
                _parse_year_from_name(display_name)
                if display_name
                else (_slug_to_title(slug), None)
            )
            films.append(ScrapedFilm(title=title, year=year, slug=slug))
        return films

    # Legacy markup: div[data-film-slug]
    for poster in soup.select("div[data-film-slug]"):
        slug = poster.get("data-film-slug", "").strip()
        if not slug:
            continue
        title = ""
        poster_url: Optional[str] = None
        img = poster.find("img")
        if img:
            if img.get("alt"):
                title = img["alt"].strip()
            src = img.get("src", "") or img.get("data-src", "")
            if src and "empty-poster" not in src:
                poster_url = src
        if not title:
            title = poster.get("data-film-name", "").strip()
        if not title:
            title = _slug_to_title(slug)
        year: Optional[int] = None
        raw_year = poster.get("data-film-release-year", "")
        if raw_year.isdigit():
            year = int(raw_year)
        else:
            m = re.search(r"-(\d{4})$", slug)
            if m:
                year = int(m.group(1))
        films.append(ScrapedFilm(title=title, year=year, slug=slug, poster_url=poster_url))

    return films


async def _scrape_list(
    username: str,
    list_path: str,
    *,
    delay: float = 1.0,
    max_pages: int = 40,
) -> list[ScrapedFilm]:
    """Generic paginated scraper for any Letterboxd film grid."""
    username = username.strip().lstrip("@").lower()
    if not username:
        raise ScrapeError("Empty username.")

    films: list[ScrapedFilm] = []
    seen_slugs: set[str] = set()

    async with httpx.AsyncClient(
        headers={"User-Agent": USER_AGENT},
        timeout=20.0,
        follow_redirects=True,
    ) as client:
        for page in range(1, max_pages + 1):
            url = (
                f"{BASE_URL}/{username}/{list_path}/"
                if page == 1
                else f"{BASE_URL}/{username}/{list_path}/page/{page}/"
            )
            try:
                resp = await client.get(url)
            except httpx.HTTPError as exc:
                raise ScrapeError(f"Network error fetching {url}: {exc}") from exc

            if resp.status_code == 404:
                if page == 1:
                    raise ScrapeError(
                        f"Letterboxd kullanıcısı '{username}' bulunamadı "
                        "(ya da liste gizli)."
                    )
                break
            if resp.status_code in (403, 429):
                # Rate limit veya erişim kısıtlaması — mevcut filmlerle devam et
                if page == 1:
                    raise ScrapeError(
                        f"Letterboxd erişimi engelledi (HTTP {resp.status_code}). "
                        "Hesap gizli olabilir."
                    )
                break  # sonraki sayfalar kısıtlıysa elimizdekiyle devam et
            if resp.status_code != 200:
                raise ScrapeError(
                    f"Letterboxd HTTP {resp.status_code} döndürdü: {url}"
                )

            page_films = _parse_page(resp.text)
            if not page_films:
                break

            for film in page_films:
                if film.slug not in seen_slugs:
                    seen_slugs.add(film.slug)
                    films.append(film)

            if delay:
                await asyncio.sleep(delay)

    return films


async def scrape_watchlist(
    username: str,
    *,
    delay: float = 1.0,
    max_pages: int = 40,
) -> list[ScrapedFilm]:
    """Kullanıcının izlemek istediği film listesini çeker."""
    return await _scrape_list(username, "watchlist", delay=delay, max_pages=max_pages)


async def scrape_watched(
    username: str,
    *,
    delay: float = 1.0,
    max_pages: int = 6,
) -> list[ScrapedFilm]:
    """Kullanıcının izlediği filmleri çeker (zevk profili için).

    Varsayılan 6 sayfa ≈ 432 film. Letterboxd /films/ sayfası
    en son izlenenden eskiye sıralıdır, bu yüzden ilk sayfalar
    güncel zevki en iyi temsil eder.
    """
    return await _scrape_list(username, "films", delay=delay, max_pages=max_pages)
