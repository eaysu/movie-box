"""Layer 1 — scrape Letterboxd film lists (watchlist and watched films).

Letterboxd has no public API, so we fetch HTML and parse the poster grid.
The CSS selectors are best-effort; Letterboxd can change its markup at any time.
"""

import asyncio
import html as _html
import logging
import random
import re
import urllib.parse
from dataclasses import dataclass, asdict
from typing import Optional

from curl_cffi.requests import AsyncSession
from bs4 import BeautifulSoup

log = logging.getLogger("moviebox")

BASE_URL = "https://letterboxd.com"


def _scraperapi_url(url: str, api_key: str) -> str:
    """Wrap a URL through ScraperAPI to bypass Cloudflare IP blocks."""
    return f"http://api.scraperapi.com?api_key={api_key}&url={urllib.parse.quote(url)}"


# ── Tarayıcı taklidi ────────────────────────────────────────────────────────
# curl-cffi `impersonate` ile Chrome/Safari TLS + HTTP/2 parmak izini taklit eder.
# Her retry'da havuzdan farklı bir parmak izi seçilir — tek bir parmak izine
# kilitli kalmak yerine, bloklandığında başka bir "tarayıcı" gibi görünürüz.
_DEFAULT_IMPERSONATE = "chrome124"
_IMPERSONATE_POOL = [
    "chrome124", "chrome123", "chrome120",
    "chrome131", "edge101", "safari17_0",
]

# Gerçek tarayıcı navigasyon başlıkları — TLS parmak izini davranışsal olarak tamamlar.
_NAV_HEADERS = {
    "Accept": (
        "text/html,application/xhtml+xml,application/xml;q=0.9,"
        "image/avif,image/webp,image/apng,*/*;q=0.8"
    ),
    "Accept-Language": "en-US,en;q=0.9",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "same-origin",
    "Sec-Fetch-User": "?1",
    "Upgrade-Insecure-Requests": "1",
}


async def _human_pause(base: float) -> None:
    """İnsan benzeri, rastgele gecikme. Sabit aralık yerine jitter + ara sıra mola.

    Düzenli aralıklarla atılan istekler bot imzasıdır; gerçek bir kullanıcı
    sayfalar arasında değişken sürelerde gezinir, ara sıra durup "okur".
    """
    if base <= 0:
        return
    d = base * random.uniform(0.7, 1.8)
    if random.random() < 0.12:
        d += random.uniform(1.5, 4.0)  # ara sıra uzun "okuma" molası
    await asyncio.sleep(d)


async def _warmup(session, username: str) -> None:
    """Doğal gezinme taklidi: anasayfa → profil. Cloudflare oturum cookie'leri kurar.

    Bir tarayıcı film listesine doğrudan girmez; önce anasayfayı ve profili
    ziyaret eder. Bu istekler cf_clearance / oturum cookie'lerini set edebilir,
    sonraki liste isteklerinin engellenme olasılığını düşürür. Hatalar kritik değil.
    """
    for url in (f"{BASE_URL}/", f"{BASE_URL}/{username}/"):
        try:
            await session.get(url, headers=_NAV_HEADERS, timeout=10)
            await _human_pause(0.5)
        except Exception:
            pass


async def _fetch_with_retry(
    session, url: str, referer: str, *, max_retries: int = 3, timeout: float = 14.0
):
    """Bir sayfayı getir; 403/429'da backoff + parmak izi rotasyonu ile tekrar dene.

    Cloudflare datacenter IP'lerini olasılıksal olarak engeller — aynı istek
    biraz bekleyip farklı parmak iziyle tekrar denendiğinde sıklıkla geçer.

    Döner: (resp | None, last_status). resp None → tüm denemeler ağ hatası ile bitti.
    Engelli (403/429) son yanıt da döndürülür; karar çağırana bırakılır.
    """
    headers = {**_NAV_HEADERS, "Referer": referer}
    resp = None
    last_status = 0
    for attempt in range(max_retries):
        impersonate = _IMPERSONATE_POOL[attempt % len(_IMPERSONATE_POOL)]
        try:
            resp = await session.get(
                url, headers=headers, timeout=timeout, impersonate=impersonate
            )
        except Exception as exc:
            last_status = -1
            log.warning("scraper: network error (attempt %d) %s: %s", attempt + 1, url, exc)
            if attempt == max_retries - 1:
                return None, last_status
            await _human_pause(1.0 * (attempt + 1))
            continue

        last_status = resp.status_code
        if resp.status_code not in (403, 429):
            return resp, resp.status_code

        # Engellendi → backoff (artan) + jitter, sonra farklı parmak iziyle tekrar
        if attempt < max_retries - 1:
            backoff = (attempt + 1) * 2.5 + random.uniform(0.5, 2.0)
            log.warning("scraper: HTTP %d on %s — retry %d/%d after %.1fs",
                        resp.status_code, url, attempt + 2, max_retries, backoff)
            await asyncio.sleep(backoff)

    return resp, last_status


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
    delay: float = 1.0,
    max_pages: int = 40,
    film_limit: int | None = None,
    max_retries: int = 3,
    scraperapi_key: str = "",
    scraperapi_max_pages: int = 2,
) -> tuple[list[ScrapedFilm], bool]:
    """Generic paginated scraper for any Letterboxd film grid.

    Strateji (kredi-dostu, kapsamlı):
      1. Tek bir oturumda doğal warm-up (anasayfa → profil) ile cookie kur.
      2. Her sayfayı curl-cffi ile getir; humanize edilmiş jitter'lı gecikmeler.
      3. 403/429 gelirse backoff + parmak izi rotasyonu ile birkaç kez tekrar dene.
      4. curl-cffi bir sayfada tamamen bloklanırsa ve bütçe varsa, SADECE o sayfa
         için ScraperAPI'ye düş (sayfa başına ~10 kredi). `scraperapi_max_pages`
         ile toplam proxy çağrısı sıkıca sınırlanır.

    film_limit: toplam bu sayıya ulaşınca durur (None = sınırsız).
    Döner: (films, complete). complete=False → tarama bir blok/hata ile yarıda
    kaldı (eksik olabilir); cache'lenmemeli. complete=True → doğal son / limit.
    """
    username = username.strip().lstrip("@").lower()
    if not username:
        raise ScrapeError("Empty username.")

    films: list[ScrapedFilm] = []
    seen_slugs: set[str] = set()
    sapi_used = 0  # ScraperAPI çağrı sayacı — kredi koruması
    complete = True  # blok/hata ile yarıda kalırsa False'a çekilir

    async with AsyncSession(impersonate=_DEFAULT_IMPERSONATE) as session:
        await _warmup(session, username)

        for page in range(1, max_pages + 1):
            direct_url = (
                f"{BASE_URL}/{username}/{list_path}/"
                if page == 1
                else f"{BASE_URL}/{username}/{list_path}/page/{page}/"
            )
            if page == 1:
                referer = f"{BASE_URL}/{username}/"
            elif page == 2:
                referer = f"{BASE_URL}/{username}/{list_path}/"
            else:
                referer = f"{BASE_URL}/{username}/{list_path}/page/{page - 1}/"

            # ── 1) curl-cffi (asıl iş gücü) — retry + parmak izi rotasyonu ──────
            resp, status = await _fetch_with_retry(
                session, direct_url, referer, max_retries=max_retries
            )

            # ── 2) Bloklandıysa ve bütçe varsa → ScraperAPI son çare (o sayfaya)
            blocked = resp is None or status in (403, 429)
            if blocked and scraperapi_key and sapi_used < scraperapi_max_pages:
                sapi_used += 1
                log.warning(
                    "scraper: curl-cffi blocked (status=%s) on %s — ScraperAPI fallback #%d/%d",
                    status, direct_url, sapi_used, scraperapi_max_pages,
                )
                try:
                    r = await session.get(
                        _scraperapi_url(direct_url, scraperapi_key),
                        headers={}, timeout=70,
                    )
                    if r.status_code in (200, 404):
                        resp, status = r, r.status_code
                    else:
                        log.warning("scraper: ScraperAPI returned %d for %s", r.status_code, direct_url)
                except Exception as exc:
                    log.warning("scraper: ScraperAPI fallback error: %s", exc)

            # ── Durum kodu değerlendirmesi ─────────────────────────────────────
            if resp is None:
                if page == 1:
                    raise ScrapeError(f"Letterboxd'a ulaşılamadı: {direct_url}")
                complete = False  # ağ hatası ile yarıda kaldı
                break
            if status == 404:
                # 404: bu sayfa yok → liste doğal olarak bitti (eksik değil).
                if page == 1:
                    raise ScrapeError(
                        f"Letterboxd kullanıcısı '{username}' bulunamadı (ya da liste gizli)."
                    )
                break
            if status in (403, 429):
                if page == 1:
                    raise ScrapeError(
                        f"Letterboxd erişimi engelledi (HTTP {status}). "
                        "Hesap gizli olabilir veya sunucu IP'si geçici olarak bloklu."
                    )
                complete = False  # bloklandı → kalan sayfalar eksik
                break
            if status != 200:
                if page == 1:
                    raise ScrapeError(f"Letterboxd HTTP {status} döndürdü: {direct_url}")
                complete = False
                break

            page_films = _parse_page(resp.text)
            if not page_films:
                if page == 1:
                    preview = resp.text[:300].replace("\n", " ")
                    log.warning("scraper: page 1 empty (status=%s). HTML preview: %s", status, preview)
                    raise ScrapeError(
                        "Letterboxd film listesi okunamadı — sunucu IP'si engellenmiş olabilir. "
                        "Birkaç dakika sonra tekrar dene."
                    )
                break  # boş sayfa = pagination doğal sonu

            new_count = 0
            for film in page_films:
                if film.slug not in seen_slugs:
                    seen_slugs.add(film.slug)
                    films.append(film)
                    new_count += 1

            # Sayfa tamamen tekrar (yeni film yok) → pagination bitti, dur.
            if new_count == 0:
                break

            if film_limit and len(films) >= film_limit:
                films = films[:film_limit]
                break

            await _human_pause(delay)

    return films, complete


async def scrape_watchlist(
    username: str,
    *,
    delay: float = 1.0,
    max_pages: int = 40,
    film_limit: int | None = None,
    max_retries: int = 3,
    scraperapi_key: str = "",
    scraperapi_max_pages: int = 2,
) -> tuple[list[ScrapedFilm], bool]:
    """Kullanıcının izlemek istediği film listesini çeker. Döner: (films, complete)."""
    return await _scrape_list(
        username, "watchlist",
        delay=delay, max_pages=max_pages, film_limit=film_limit,
        max_retries=max_retries,
        scraperapi_key=scraperapi_key, scraperapi_max_pages=scraperapi_max_pages,
    )


async def scrape_diary(
    username: str,
    *,
    max_pages: int = 5,
    film_limit: int = 250,
    max_retries: int = 3,
    scraperapi_key: str = "",
    scraperapi_max_pages: int = 2,
) -> tuple[list[ScrapedFilm], bool]:
    """Diary HTML sayfalarından ek film listesi çeker. Döner: (films, complete)."""
    return await _scrape_list(
        username, "films/diary",
        delay=0.6, max_pages=max_pages, film_limit=film_limit,
        max_retries=max_retries,
        scraperapi_key=scraperapi_key, scraperapi_max_pages=scraperapi_max_pages,
    )


async def _scrape_watched_rss(username: str) -> list[ScrapedFilm]:
    """RSS feed'den en son ~50 izlenen filmi çeker (rating dahil).

    HTML scrape ile birleştirilerek kapsam genişletilir.
    Başarısız olursa boş liste döner — kritik değil.
    """
    url = f"{BASE_URL}/{username}/rss/"
    try:
        async with AsyncSession(impersonate=_DEFAULT_IMPERSONATE) as session:
            resp = await session.get(url, headers=_NAV_HEADERS, timeout=20)
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
    delay: float = 1.0,
    max_pages: int = 10,
    film_limit: int = 100,
    max_retries: int = 3,
    scraperapi_key: str = "",
    scraperapi_max_pages: int = 2,
) -> tuple[list[ScrapedFilm], bool]:
    """Kullanıcının en son izlediği filmleri çeker (zevk profili için).

    Öncelik — hepsi tarihli/kronolojik, en yeni önce:
      1. Diary sayfaları (film_limit'e yetecek kadar, ~50 kayıt/sayfa)
      2. /rss/ — en son ~50 diary kaydı, diary'nin kaçırdığını tamamlar
      3. /films/ HTML (tarihsiz, sıra garantisiz) — sadece 1+2 film_limit'i
         doldurmazsa (az/dağınık diary kaydı olan kullanıcılar için) dolgu.
    film_limit hard cap olarak uygulanır (varsayılan 100) — "en son izlenen N film".
    Döner: (films, complete) — complete, taramanın bir blokla yarıda kalıp kalmadığı.
    """
    diary_pages = max(1, -(-film_limit // 50))
    try:
        diary_films, complete = await scrape_diary(
            username,
            max_pages=diary_pages,
            film_limit=film_limit,
            max_retries=max_retries,
            scraperapi_key=scraperapi_key,
            scraperapi_max_pages=scraperapi_max_pages,
        )
    except ScrapeError:
        diary_films, complete = [], True  # diary boş/gizli olabilir, kritik değil

    seen: set[str] = {f.slug for f in diary_films if f.slug}
    combined = list(diary_films)

    if len(combined) < film_limit:
        rss_films = await _scrape_watched_rss(username)
        for f in rss_films:
            if f.slug and f.slug not in seen:
                seen.add(f.slug)
                combined.append(f)
            elif not f.slug:
                key = f"{f.title.lower()}:{f.year}"
                if key not in seen:
                    seen.add(key)
                    combined.append(f)

    if len(combined) < film_limit:
        try:
            html_films, html_complete = await _scrape_list(
                username, "films",
                delay=delay,
                max_pages=max_pages,
                film_limit=film_limit,
                max_retries=max_retries,
                scraperapi_key=scraperapi_key,
                scraperapi_max_pages=scraperapi_max_pages,
            )
        except ScrapeError:
            html_films, html_complete = [], complete
        complete = complete and html_complete
        for f in html_films:
            if len(combined) >= film_limit:
                break
            if f.slug and f.slug not in seen:
                seen.add(f.slug)
                combined.append(f)

    return combined[:film_limit], complete
