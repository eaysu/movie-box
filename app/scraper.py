"""Layer 1 — scrape Letterboxd film lists (watchlist and watched films).

Letterboxd has no public API, so we fetch HTML and parse the poster grid.
The CSS selectors are best-effort; Letterboxd can change its markup at any time.
"""

import asyncio
import html as _html
import logging
import re
from dataclasses import dataclass, asdict
from typing import Optional

from curl_cffi.requests import AsyncSession
from bs4 import BeautifulSoup

log = logging.getLogger("moviebox")

BASE_URL = "https://letterboxd.com"

# curl-cffi impersonate="chrome124" otomatik olarak Chrome TLS + HTTP/2 parmak izi kullanır.
# Sadece navigasyon için Referer gibi ek başlıklar gerektiğinde kullanılır.
_CHROME_IMPERSONATE = "chrome124"


class ScrapeError(Exception):
    """Raised when a Letterboxd page cannot be retrieved."""


@dataclass
class ScrapedFilm:
    title: str
    year: Optional[int]
    slug: str
    poster_url: Optional[str] = None
    user_rating: Optional[float] = None  # Letterboxd 0.5-5.0 arası

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

    def _extract_poster(el) -> ScrapedFilm | None:
        slug = (
            el.get("data-item-slug")
            or el.get("data-film-slug")
            or el.get("data-target-link", "").strip("/").split("/")[-1]
        ).strip()
        if not slug or slug in ("", "/"):
            return None
        display_name = _html.unescape((
            el.get("data-item-full-display-name", "")
            or el.get("data-item-name", "")
            or el.get("data-film-name", "")
        ).strip())
        title, year = (
            _parse_year_from_name(display_name)
            if display_name
            else (_slug_to_title(slug), None)
        )
        if not year:
            raw_year = el.get("data-film-release-year", "")
            if raw_year.isdigit():
                year = int(raw_year)
            else:
                m = re.search(r"-(\d{4})$", slug)
                if m:
                    year = int(m.group(1))
        poster_url: Optional[str] = None
        img = el.find("img")
        if img:
            if img.get("alt") and not title:
                title = img["alt"].strip()
            # Letterboxd bazen src, bazen data-src, bazen srcset kullanır.
            # srcset örneği: "https://a.ltrbxd.com/.../0-70-0-105-crop.jpg 1x, ...2x"
            src = img.get("src", "") or img.get("data-src", "")
            if not src:
                srcset = img.get("srcset", "")
                if srcset:
                    src = srcset.split(",")[0].strip().split(" ")[0]
            if src and "empty-poster" not in src and src.startswith("http"):
                poster_url = src
        if not title:
            title = _slug_to_title(slug)
        return ScrapedFilm(title=title, year=year, slug=slug, poster_url=poster_url)

    # 2024+ LazyPoster: data-item-slug
    candidates = soup.select("div[data-item-slug]")
    # Legacy: data-film-slug
    if not candidates:
        candidates = soup.select("div[data-film-slug]")
    # Newer list markup: li[data-film-slug] or li[data-item-slug]
    if not candidates:
        candidates = soup.select("li[data-film-slug], li[data-item-slug]")
    # poster-list items with data-target-link pointing to /film/slug/
    if not candidates:
        candidates = [
            el for el in soup.select("[data-target-link]")
            if "/film/" in el.get("data-target-link", "")
        ]

    seen: set[str] = set()
    for el in candidates:
        film = _extract_poster(el)
        if film and film.slug not in seen:
            seen.add(film.slug)
            films.append(film)

    return films


async def _scrape_list(
    username: str,
    list_path: str,
    *,
    delay: float = 0.4,
    max_pages: int = 40,
    film_limit: int | None = None,
) -> list[ScrapedFilm]:
    """Generic paginated scraper for any Letterboxd film grid.

    curl-cffi ile Chrome TLS parmak izi taklit edilerek Cloudflare bypass yapılır.
    film_limit: toplam bu sayıya ulaşınca durur (None = sınırsız).
    """
    username = username.strip().lstrip("@").lower()
    if not username:
        raise ScrapeError("Empty username.")

    films: list[ScrapedFilm] = []
    seen_slugs: set[str] = set()

    async with AsyncSession(impersonate=_CHROME_IMPERSONATE) as session:
        # Warm-up: profil sayfasını ziyaret et → Cloudflare oturum cookie'si kurar
        try:
            await session.get(f"{BASE_URL}/{username}/", timeout=20)
        except Exception:
            pass  # non-critical

        for page in range(1, max_pages + 1):
            url = (
                f"{BASE_URL}/{username}/{list_path}/"
                if page == 1
                else f"{BASE_URL}/{username}/{list_path}/page/{page}/"
            )

            # Referer: önceki sayfa URL'si — gerçek tarayıcı gezintisini taklit eder
            if page == 1:
                referer = f"{BASE_URL}/{username}/"
            elif page == 2:
                referer = f"{BASE_URL}/{username}/{list_path}/"
            else:
                referer = f"{BASE_URL}/{username}/{list_path}/page/{page - 1}/"

            try:
                resp = await session.get(url, headers={"Referer": referer}, timeout=20)
            except Exception as exc:
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


async def scrape_diary(
    username: str,
    *,
    max_pages: int = 5,
    film_limit: int = 250,
) -> list[ScrapedFilm]:
    """Diary HTML sayfalarından ek film listesi çeker.

    RSS son 50 girişi verir; diary HTML sayfaları 2+ daha eski izlemeleri sağlar.
    Cloudflare /films/page/2+/ 'yı engelliyor ama /films/diary/page/N/ genellikle açık.
    Hata durumunda ScrapeError fırlatır — sarmalayıcı [] döndürmeli.
    """
    return await _scrape_list(username, "films/diary", delay=0.5, max_pages=max_pages, film_limit=film_limit)


async def _scrape_watched_rss(username: str) -> list[ScrapedFilm]:
    """RSS feed'den en son ~50 izlenen filmi çeker (rating dahil).

    HTML scrape ile birleştirilerek kapsam genişletilir.
    Başarısız olursa boş liste döner — kritik değil.
    """
    url = f"{BASE_URL}/{username}/rss/"
    try:
        async with AsyncSession(impersonate=_CHROME_IMPERSONATE) as session:
            resp = await session.get(url, timeout=20)
        if resp.status_code != 200:
            return []
    except Exception:
        return []

    films: list[ScrapedFilm] = []
    entries = re.findall(r"<item>(.*?)</item>", resp.text, re.DOTALL)
    for entry in entries:
        title_m  = re.search(r"<letterboxd:filmTitle>(.*?)</letterboxd:filmTitle>", entry)
        year_m   = re.search(r"<letterboxd:filmYear>(\d{4})</letterboxd:filmYear>", entry)
        link_m   = re.search(r"<link>(https://letterboxd\.com[^<]+)</link>", entry)
        rating_m = re.search(r"<letterboxd:memberRating>([\d.]+)</letterboxd:memberRating>", entry)
        if not title_m:
            continue
        title  = _html.unescape(title_m.group(1).strip())
        year   = int(year_m.group(1)) if year_m else None
        rating = float(rating_m.group(1)) if rating_m else None
        slug   = ""
        if link_m:
            slug_match = re.search(r"/film/([^/]+)/", link_m.group(1))
            if slug_match:
                slug = slug_match.group(1)
        films.append(ScrapedFilm(title=title, year=year, slug=slug, user_rating=rating))

    return films


async def scrape_watched(
    username: str,
    *,
    delay: float = 0.4,
    max_pages: int = 10,
    film_limit: int = 300,
) -> list[ScrapedFilm]:
    """Kullanıcının izlediği filmleri çeker (zevk profili için).

    Strateji:
      1. /films/ HTML — curl-cffi ile Chrome parmak izi → sayfa N'e kadar erişilebilir
      2. /rss/ — en son ~50 diary kaydı (rating bilgisi içerir)
    İki kaynak slug ile tekilleştirilip birleştirilir.
    film_limit hard cap olarak uygulanır (varsayılan 300).
    """
    html_films = await _scrape_list(
        username, "films",
        delay=delay,
        max_pages=max_pages,   # 403 gelirse scraper sessizce durur
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
