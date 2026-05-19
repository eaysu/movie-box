"""Layer 1 — scrape Letterboxd film lists (watchlist and watched films).

Letterboxd has no public API, so we fetch HTML and parse the poster grid.
The CSS selectors are best-effort; Letterboxd can change its markup at any time.
"""

import asyncio
import logging
import re
from dataclasses import dataclass, asdict
from typing import Optional

import httpx
from bs4 import BeautifulSoup

log = logging.getLogger("moviebox")

BASE_URL = "https://letterboxd.com"

# Gerçek bir tarayıcıya benzer User-Agent — Letterboxd bot tespitini azaltır
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/125.0.0.0 Safari/537.36"
)

BASE_HEADERS = {
    "User-Agent": USER_AGENT,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate",
    "DNT": "1",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1",
}


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
    film_limit: int | None = None,
) -> list[ScrapedFilm]:
    """Generic paginated scraper for any Letterboxd film grid.

    film_limit: toplam bu sayıya ulaşınca durur (None = sınırsız).
    """
    username = username.strip().lstrip("@").lower()
    if not username:
        raise ScrapeError("Empty username.")

    films: list[ScrapedFilm] = []
    seen_slugs: set[str] = set()

    async with httpx.AsyncClient(
        headers=BASE_HEADERS,
        timeout=20.0,
        follow_redirects=True,
    ) as client:
        for page in range(1, max_pages + 1):
            if page == 1:
                url = f"{BASE_URL}/{username}/{list_path}/"
            else:
                url = f"{BASE_URL}/{username}/{list_path}/page/{page}/"

            # Referer: önceki sayfa URL'si — Letterboxd bot tespitini azaltır
            headers = {"Referer": f"{BASE_URL}/{username}/{list_path}/"}
            if page > 1:
                prev = (
                    f"{BASE_URL}/{username}/{list_path}/"
                    if page == 2
                    else f"{BASE_URL}/{username}/{list_path}/page/{page - 1}/"
                )
                headers["Referer"] = prev

            try:
                resp = await client.get(url, headers=headers)
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
                if page == 1:
                    # 200 ama film yok → büyük ihtimalle bot/captcha sayfası
                    preview = resp.text[:300].replace("\n", " ")
                    log.warning("scraper: page 1 empty (status=%s). HTML preview: %s", resp.status_code, preview)
                    raise ScrapeError(
                        "Letterboxd film listesi okunamadı — sunucu IP'si engellenmiş olabilir. "
                        "Birkaç dakika sonra tekrar dene."
                    )
                break

            for film in page_films:
                if film.slug not in seen_slugs:
                    seen_slugs.add(film.slug)
                    films.append(film)

            # Hard limit'e ulaştıysak dur
            if film_limit and len(films) >= film_limit:
                films = films[:film_limit]
                break

            if delay:
                await asyncio.sleep(delay)

    return films


async def scrape_watchlist(
    username: str,
    *,
    delay: float = 1.0,
    max_pages: int = 40,
    film_limit: int | None = None,
) -> list[ScrapedFilm]:
    """Kullanıcının izlemek istediği film listesini çeker."""
    return await _scrape_list(username, "watchlist", delay=delay, max_pages=max_pages, film_limit=film_limit)


async def _scrape_watched_rss(username: str) -> list[ScrapedFilm]:
    """RSS feed'den en son 50 izlenen filmi çeker.

    Letterboxd /films/page/2+/ 403 döndürdüğü için RSS ile
    HTML page-1'i birleştirip daha geniş bir örneklem elde ediyoruz.
    Başarısız olursa boş liste döner — kritik değil.
    """
    url = f"{BASE_URL}/{username}/rss/"
    try:
        async with httpx.AsyncClient(
            headers=BASE_HEADERS, timeout=20.0, follow_redirects=True
        ) as client:
            resp = await client.get(url)
        if resp.status_code != 200:
            return []
    except httpx.HTTPError:
        return []

    films: list[ScrapedFilm] = []
    entries = re.findall(r"<item>(.*?)</item>", resp.text, re.DOTALL)
    for entry in entries:
        title_m = re.search(r"<letterboxd:filmTitle>(.*?)</letterboxd:filmTitle>", entry)
        year_m  = re.search(r"<letterboxd:filmYear>(\d{4})</letterboxd:filmYear>", entry)
        link_m  = re.search(r"<link>(https://letterboxd\.com[^<]+)</link>", entry)
        if not title_m:
            continue
        title = title_m.group(1).strip()
        year  = int(year_m.group(1)) if year_m else None
        slug  = ""
        if link_m:
            slug_match = re.search(r"/film/([^/]+)/", link_m.group(1))
            if slug_match:
                slug = slug_match.group(1)
        films.append(ScrapedFilm(title=title, year=year, slug=slug))

    return films


async def scrape_watched(
    username: str,
    *,
    delay: float = 1.0,
    max_pages: int = 10,
    film_limit: int = 300,
) -> list[ScrapedFilm]:
    """Kullanıcının izlediği filmleri çeker (zevk profili için).

    Strateji:
      1. /films/ HTML — sayfa 1 (≈72 film, sayfa 2+ Letterboxd tarafından engelleniyor)
      2. /rss/ — en son 50 diary kaydı (engelleme yok)
    İki kaynak slug ile tekilleştirilip birleştirilir.
    film_limit hard cap olarak uygulanır (varsayılan 300).
    """
    html_films = await _scrape_list(
        username, "films",
        delay=0,         # tek sayfa, delay gereksiz
        max_pages=1,
        film_limit=film_limit,
    )
    rss_films = await _scrape_watched_rss(username)

    seen: set[str] = {f.slug for f in html_films if f.slug}
    combined = list(html_films)
    for f in rss_films:
        if f.slug and f.slug not in seen:
            seen.add(f.slug)
            combined.append(f)
        elif not f.slug:
            # Slug yoksa başlık+yıl ile tekrar kontrolü yap
            key = f"{f.title.lower()}:{f.year}"
            if key not in seen:
                seen.add(key)
                combined.append(f)

    return combined[:film_limit]
