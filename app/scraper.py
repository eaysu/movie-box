"""Layer 1 — scrape a public Letterboxd watchlist.

Letterboxd has no public API, so we fetch the watchlist HTML pages and parse
the poster grid. The CSS selectors here are best-effort: Letterboxd can change
its markup at any time, in which case `_parse_page` may need updating. The
parser tries several selectors and fails loudly (empty result) rather than
silently when the structure no longer matches.
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
    "personal project; +https://github.com/yourname/letterboxd-recommender)"
)


class ScrapeError(Exception):
    """Raised when a watchlist cannot be retrieved."""


@dataclass
class ScrapedFilm:
    title: str
    year: Optional[int]
    slug: str
    poster_url: Optional[str] = None

    def to_dict(self) -> dict:
        return asdict(self)


def _slug_to_title(slug: str) -> str:
    """Fallback: turn 'in-the-mood-for-love' into 'In The Mood For Love'."""
    return slug.replace("-", " ").strip().title()


def _parse_year_from_name(name: str) -> tuple[str, Optional[int]]:
    """Parse 'Wolf (1994)' → ('Wolf', 1994). Returns (name, None) if no year."""
    m = re.search(r"^(.*?)\s*\((\d{4})\)\s*$", name.strip())
    if m:
        return m.group(1).strip(), int(m.group(2))
    return name.strip(), None


def _parse_page(html: str) -> list[ScrapedFilm]:
    """Extract films from one watchlist page.

    Tries the current LazyPoster structure first (data-item-slug), then falls
    back to the old data-film-slug layout for forward-compatibility.
    """
    soup = BeautifulSoup(html, "lxml")
    films: list[ScrapedFilm] = []

    # Current Letterboxd markup (2024+): each film is a div with
    # data-component-class="LazyPoster" and carries data-item-slug,
    # data-item-name, data-item-full-display-name.
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
            title, year = _parse_year_from_name(display_name) if display_name else (_slug_to_title(slug), None)
            films.append(ScrapedFilm(title=title, year=year, slug=slug))
        return films

    # Legacy Letterboxd markup: div[data-film-slug].
    posters = soup.select("div[data-film-slug]")
    for poster in posters:
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


async def scrape_watchlist(
    username: str,
    *,
    delay: float = 1.0,
    max_pages: int = 40,
) -> list[ScrapedFilm]:
    """Fetch every film on a user's public watchlist.

    Args:
        username: the Letterboxd handle (without the @).
        delay: seconds to wait between page requests (be polite).
        max_pages: hard cap so a huge watchlist can't run forever.

    Raises:
        ScrapeError: if the user does not exist or the page can't be read.
    """
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
            if page == 1:
                url = f"{BASE_URL}/{username}/watchlist/"
            else:
                url = f"{BASE_URL}/{username}/watchlist/page/{page}/"

            try:
                resp = await client.get(url)
            except httpx.HTTPError as exc:
                raise ScrapeError(f"Network error fetching {url}: {exc}") from exc

            if resp.status_code == 404:
                if page == 1:
                    raise ScrapeError(
                        f"No Letterboxd user '{username}' (or the watchlist is private)."
                    )
                break  # ran past the last page
            if resp.status_code != 200:
                raise ScrapeError(
                    f"Letterboxd returned HTTP {resp.status_code} for {url}."
                )

            page_films = _parse_page(resp.text)
            if not page_films:
                break  # no more films

            for film in page_films:
                if film.slug not in seen_slugs:
                    seen_slugs.add(film.slug)
                    films.append(film)

            if delay:
                await asyncio.sleep(delay)

    return films
