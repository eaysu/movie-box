"""Sinema gündemi — ingest, title matching and the weekly per-user digest.

Three layers feed one table:

* ``release``   — TMDb ``now_playing`` for the region. Contractual data, cannot
  break, and needs no showtimes.
* ``repertory`` — art-house programmes, parsed from selectors stored on the
  venue row rather than in code, so a site redesign is a row edit.
* ``festival``  — same shape as repertory, kept apart only for labelling.

The digest is what the profile card renders: films on the member's watchlist
that are playing, films they rated highly that are back on screen, and new
releases that fit their taste. All three sections are built from rows this
module wrote, so the card never waits on a scrape.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import re
import unicodedata
import uuid
from datetime import date, datetime, time, timedelta, timezone

log = logging.getLogger("moviebox")

RELEASE_VENUE_SLUG = "tr-vizyon"
SECTION_LIMIT = 3
# Istanbul time, fixed: the bulletin is a Turkish cinema programme, so its week
# should not roll over at the server's UTC midnight.
LOCAL_TZ = timezone(timedelta(hours=3))


def week_start(now: datetime | None = None) -> date:
    """Monday of the current local week — the digest's identity."""
    current = (now or datetime.now(LOCAL_TZ)).astimezone(LOCAL_TZ).date()
    return current - timedelta(days=current.weekday())


def week_bounds(now: datetime | None = None) -> tuple[datetime, datetime]:
    start = week_start(now)
    begin = datetime.combine(start, time.min, tzinfo=LOCAL_TZ)
    return begin, begin + timedelta(days=7)


# ── Title matching ─────────────────────────────────────────────────────────
_PUNCT = re.compile(r"[^\w\s]", re.UNICODE)
_SPACES = re.compile(r"\s+")
_TRAILING_YEAR = re.compile(r"\s*\(?(19|20)\d{2}\)?\s*$")


def normalize_title(value: str) -> str:
    """Casefold a title for comparison, with Turkish dotted/dotless i handled.

    ``str.lower`` maps ``I`` to ``i``, which is wrong for Turkish (``I`` is the
    capital of ``ı``). Comparing "KIŞ UYKUSU" with "Kış Uykusu" needs the
    explicit mapping below before the generic casefold.
    """
    text = unicodedata.normalize("NFC", str(value or "")).strip()
    text = _TRAILING_YEAR.sub("", text)
    text = text.replace("İ", "i").replace("I", "ı").replace("ı", "i")
    text = text.casefold()
    text = _PUNCT.sub(" ", text)
    return _SPACES.sub(" ", text).strip()


def _year_close(left, right, *, slack: int = 1) -> bool:
    try:
        return abs(int(left) - int(right)) <= slack
    except (TypeError, ValueError):
        return True


async def resolve_screening_title(
    title_raw: str,
    year: int | None,
    *,
    catalog: dict[str, dict],
    enricher=None,
) -> dict:
    """Resolve one programme line to a film.

    ``catalog`` maps a normalized title to a row we already hold, so the common
    case costs nothing. Only genuinely unknown titles reach TMDb, first in
    Turkish (the distribution title is what a cinema prints) and then through
    alternative titles for films released here under a translated name.
    """
    key = normalize_title(title_raw)
    if not key:
        return {"match_status": "unresolved"}

    # Some venues print both titles on one line ("The Unknown / İçimdeki
    # Yabancı"). Either half is a real title; try them before giving up on the
    # combined string, which matches nothing anywhere.
    if "/" in str(title_raw):
        parts = [part.strip() for part in str(title_raw).split("/") if part.strip()]
        if len(parts) > 1:
            for part in parts:
                found = await resolve_screening_title(
                    part, year, catalog=catalog, enricher=enricher
                )
                if found.get("match_status") == "matched":
                    return found

    local = catalog.get(key)
    if local and _year_close(local.get("release_year"), year):
        return {
            "tmdb_id": local.get("tmdb_id"),
            "film_slug": local.get("film_slug"),
            "poster_url": local.get("poster_url"),
            "year": local.get("release_year") or year,
            "match_status": "matched",
        }

    if enricher is None:
        return {"match_status": "unresolved"}

    candidates = []
    for language in ("tr-TR", "en-US"):
        try:
            found = await enricher.search_movie_candidates(
                title_raw, year=year, language=language
            )
        except Exception:
            found = []
        candidates.extend(found or [])
        if candidates:
            break

    exact = [
        item for item in candidates
        if normalize_title(item.get("title")) == key
        or normalize_title(item.get("original_title")) == key
    ]
    pool = exact or candidates
    if not pool:
        return {"match_status": "unresolved"}

    # A year only disambiguates when the programme actually printed one; with no
    # year, `_year_close` accepts everything and must not be read as evidence.
    dated = (
        [item for item in pool if _year_close(item.get("year"), year, slack=1)]
        if year is not None else []
    )

    if len(exact) > 1:
        if len(dated) != 1:
            # Two films share this title and nothing separates them. Say so
            # rather than printing the wrong one on someone's card.
            return {"match_status": "ambiguous"}
        best, status = dated[0], "matched"
    else:
        pool = dated or pool
        best = pool[0]
        status = "matched" if (exact or dated) else "ambiguous"

    return {
        "tmdb_id": best.get("tmdb_id"),
        "poster_url": best.get("poster_url"),
        "year": best.get("year") or year,
        "match_status": status,
    }


# ── Ingest ─────────────────────────────────────────────────────────────────
async def ingest_release_layer(service, settings, *, enricher) -> int:
    """Refresh the nationwide release layer. Returns the row count written."""
    token = str(uuid.uuid4())
    claimed = await asyncio.to_thread(
        service.claim_venue_ingest,
        RELEASE_VENUE_SLUG,
        token,
        600,
        max(1, settings.bulletin_ingest_interval_hours) * 3600,
    )
    if not claimed:
        return 0

    run_id = str(uuid.uuid4())
    try:
        films = await enricher.fetch_now_playing(region=settings.bulletin_region)
        rows = [
            {
                "title_raw": film["title"],
                "year": film.get("year"),
                "tmdb_id": film.get("tmdb_id"),
                "poster_url": film.get("poster_url") or "",
                "match_status": "matched",
                "url": "",
            }
            for film in films
            if film.get("title")
        ]
        if not rows:
            return 0
        written = await asyncio.to_thread(
            service.upsert_screenings, RELEASE_VENUE_SLUG, rows, run_id
        )
        log.warning("bulletin release layer ingested rows=%d", written)
        return written
    except Exception as exc:  # noqa: BLE001 - a venue failure must stay local
        await asyncio.to_thread(
            service.record_venue_failure, RELEASE_VENUE_SLUG, str(exc)[:500]
        )
        log.warning("bulletin release layer failed: %s", exc)
        return 0


def parse_programme(html: str, config: dict, base_url: str) -> list[dict]:
    """Turn a venue page into programme rows using the venue's own config.

    Three strategies cover every venue seen so far, and each venue picks one:

    * ``attr`` — the item element carries the title in a data attribute. The
      sturdiest, because it survives any visual redesign.
    * ``css``  — item container plus a title selector inside it.
    * ``link`` — anchors whose href matches a pattern; the link text is the
      title. Useful when a site has no stable class names but stable URLs.
    """
    from bs4 import BeautifulSoup  # imported lazily: ingest-only dependency

    soup = BeautifulSoup(html or "", "lxml")
    strategy = config.get("strategy") or "css"
    # Call-to-action anchors ("BİLETİNİ AL", "Detaylar") sit next to the real
    # ones and match the same URL pattern, so they are excluded by name.
    skip = {normalize_title(item) for item in (config.get("skip_titles") or [])}
    rows: list[dict] = []

    def _abs(href: str) -> str:
        href = (href or "").strip()
        if not href:
            return ""
        if href.startswith("http"):
            return href
        from urllib.parse import urljoin

        return urljoin(base_url, href)

    def _poster(node) -> str:
        selector = config.get("poster_selector")
        image = node.select_one(selector) if selector else node.find("img")
        if not image:
            return ""
        src = image.get("src") or image.get("data-src") or ""
        return _abs(src) if src and not src.startswith("data:") else ""

    if strategy == "link":
        pattern = re.compile(config.get("href_pattern") or r".")
        for anchor in soup.find_all("a", href=True):
            if not pattern.search(anchor["href"]):
                continue
            title = anchor.get("title") or anchor.get_text(" ", strip=True)
            title = _SPACES.sub(" ", str(title or "")).strip()
            if not title or normalize_title(title) in skip:
                continue
            rows.append({
                "title_raw": title,
                "url": _abs(anchor["href"]),
                "poster_url": _poster(anchor),
            })
    else:
        for node in soup.select(config.get("item_selector") or ""):
            if strategy == "attr":
                title = node.get(config.get("title_attr") or "data-title") or ""
            else:
                selector = config.get("title_selector")
                found = node.select_one(selector) if selector else None
                title = found.get_text(" ", strip=True) if found else ""
            title = _SPACES.sub(" ", str(title or "")).strip()
            if not title or normalize_title(title) in skip:
                continue
            link = ""
            if config.get("link_attr"):
                link = node.get(config["link_attr"]) or ""
            if not link:
                anchor = node.select_one(config.get("link_selector") or "a[href]")
                link = anchor.get("href") if anchor and anchor.get("href") else ""
            rows.append({
                "title_raw": title,
                "url": _abs(link),
                "poster_url": _poster(node),
            })

    # The same film often appears in several blocks of one page.
    unique: dict[str, dict] = {}
    for row in rows:
        unique.setdefault(normalize_title(row["title_raw"]), row)
    return list(unique.values())[: int(config.get("limit") or 60)]


async def fetch_venue_page(venue: dict) -> str:
    """One polite GET per venue. Never retried aggressively: a venue that is
    down simply misses this run."""
    import httpx

    url = venue.get("source_url") or ""
    if not url:
        return ""
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (compatible; MovieboxdBot/1.0; +https://movieboxd.onrender.com)"
        ),
        "Accept-Language": "tr,en;q=0.8",
    }
    async with httpx.AsyncClient(timeout=25, follow_redirects=True, headers=headers) as client:
        response = await client.get(url)
        response.raise_for_status()
        return response.text


async def ingest_venues(service, *, enricher, catalog=None) -> int:
    """Refresh every active repertory/festival venue, independently.

    Each venue is claimed, fetched and written on its own, so one broken site
    cannot take the bulletin down with it.
    """
    venues = await asyncio.to_thread(service.list_active_venues)
    total = 0
    for venue in venues:
        if venue.get("kind") == "release":
            continue
        total += await ingest_repertory_venue(
            service,
            venue,
            fetch_page=_fetch_and_parse,
            enricher=enricher,
            catalog=catalog or {},
        )
    return total


async def _fetch_and_parse(venue: dict) -> list[dict]:
    html = await fetch_venue_page(venue)
    source = venue.get("source_url") or ""
    rows = parse_programme(html, venue.get("config") or {}, source)
    # Venues whose listing links are JavaScript handlers leave no per-film URL;
    # point those at the venue's own programme page rather than nowhere.
    for row in rows:
        if not row.get("url"):
            row["url"] = source
    return rows


async def ingest_repertory_venue(service, venue, *, fetch_page, enricher, catalog) -> int:
    """Parse one venue with the selectors stored on its own row.

    A venue that breaks records its error and returns zero; the bulletin still
    ships with whatever the other venues produced.
    """
    slug = venue.get("slug") or ""
    token = str(uuid.uuid4())
    claimed = await asyncio.to_thread(service.claim_venue_ingest, slug, token, 600, 43200)
    if not claimed:
        return 0

    run_id = str(uuid.uuid4())
    try:
        entries = await fetch_page(venue)
        rows = []
        for entry in entries:
            resolved = await resolve_screening_title(
                entry.get("title_raw", ""),
                entry.get("year"),
                catalog=catalog,
                enricher=enricher,
            )
            rows.append({**entry, **resolved})
        if not rows:
            return 0
        return await asyncio.to_thread(service.upsert_screenings, slug, rows, run_id)
    except Exception as exc:  # noqa: BLE001
        await asyncio.to_thread(service.record_venue_failure, slug, str(exc)[:500])
        log.warning("bulletin venue %s failed: %s", slug, exc)
        return 0


# ── Digest ─────────────────────────────────────────────────────────────────
_GENRE_TR = {
    "Action": "Aksiyon", "Adventure": "Macera", "Animation": "Animasyon",
    "Comedy": "Komedi", "Crime": "Suç", "Documentary": "Belgesel", "Drama": "Dram",
    "Family": "Aile", "Fantasy": "Fantastik", "History": "Tarih", "Horror": "Korku",
    "Music": "Müzik", "Mystery": "Gizem", "Romance": "Romantik",
    "Science Fiction": "Bilim Kurgu", "Thriller": "Gerilim", "War": "Savaş",
    "Western": "Western",
}


def _film_card(row: dict, extra: dict | None = None) -> dict:
    card = {
        "title": row.get("title") or row.get("title_raw") or "",
        "year": row.get("year"),
        "tmdb_id": row.get("tmdb_id"),
        "slug": row.get("film_slug") or "",
        "poster_url": row.get("poster_url") or "",
        "venue": row.get("venue_name") or "",
        "venue_url": row.get("url") or "",
        "starts_at": row.get("starts_at"),
    }
    card.update(extra or {})
    return card


def build_digest(screenings: list[dict], watched: list[dict], watchlist, taste) -> dict:
    """Shape one member's week from rows already in the database.

    Sections are ordered by how directly they can be acted on: something you
    already wanted to see, then something you loved that is back, then a new
    release that fits. An empty section is omitted, never padded.
    """
    # A watchlist entry may arrive as a slug string or as a full film row; a
    # screening may only know its tmdb_id, so both keys are indexed.
    wanted_slugs: set[str] = set()
    wanted_tmdb: set[int] = set()
    for item in watchlist or []:
        if isinstance(item, str):
            wanted_slugs.add(item)
            continue
        if not isinstance(item, dict):
            continue
        if item.get("slug"):
            wanted_slugs.add(item["slug"])
        if item.get("tmdb_id"):
            with contextlib.suppress(TypeError, ValueError):
                wanted_tmdb.add(int(item["tmdb_id"]))
    watched_by_tmdb: dict[int, dict] = {}
    watched_by_title: dict[str, dict] = {}
    for row in watched or []:
        if row.get("tmdb_id"):
            watched_by_tmdb[int(row["tmdb_id"])] = row
        title = normalize_title(row.get("title"))
        if title:
            watched_by_title[title] = row

    def _seen(row: dict) -> dict | None:
        tmdb_id = row.get("tmdb_id")
        if tmdb_id and int(tmdb_id) in watched_by_tmdb:
            return watched_by_tmdb[int(tmdb_id)]
        return watched_by_title.get(normalize_title(row.get("title_raw")))

    on_watchlist: list[dict] = []
    back_on_screen: list[dict] = []
    fits_taste: list[dict] = []
    genres = {str(genre).lower() for genre in (taste or {}).get("top_genres", []) if genre}
    directors = {str(name).lower() for name in (taste or {}).get("top_directors", []) if name}

    for row in screenings or []:
        seen = _seen(row)
        slug = row.get("film_slug") or ""
        if seen:
            rating = seen.get("user_rating")
            if seen.get("rating_observed") and rating and float(rating) >= 4:
                back_on_screen.append(_film_card(row, {
                    "slug": slug or seen.get("film_slug") or "",
                    "note": f"Bu filme {float(rating):.1f} vermiştin",
                    "user_rating": float(rating),
                }))
            continue
        tmdb_id = row.get("tmdb_id")
        on_list = (slug and slug in wanted_slugs) or (
            tmdb_id is not None and int(tmdb_id) in wanted_tmdb
        )
        if on_list:
            on_watchlist.append(_film_card(row, {"note": "İzleme listende"}))
            continue
        director = str(row.get("director") or "").lower()
        row_genres = {str(genre).lower() for genre in (row.get("genres") or [])}
        if director and director in directors:
            fits_taste.append(_film_card(row, {"note": f"{row.get('director')} filmi"}))
        elif row_genres & genres:
            match = sorted(row_genres & genres)[0].title()
            fits_taste.append(_film_card(row, {
                "note": f"{_GENRE_TR.get(match, match)} tarafında",
            }))

    def _dedupe(cards: list[dict]) -> list[dict]:
        """One film is one card, however many venues are showing it."""
        merged: dict[str, dict] = {}
        for card in cards:
            key = str(card.get("tmdb_id") or card.get("slug") or normalize_title(card["title"]))
            existing = merged.get(key)
            if not existing:
                merged[key] = card
                continue
            venues = [existing.get("venue"), card.get("venue")]
            existing["venue"] = " · ".join(
                dict.fromkeys(venue for venue in venues if venue)
            )
        return list(merged.values())

    sections = [
        ("watchlist", "İzleme listende ve perdede", _dedupe(on_watchlist)),
        ("back", "Tekrar perdede", _dedupe(back_on_screen)),
        ("taste", "Zevkine uyan yeni vizyon", _dedupe(fits_taste)),
    ]
    return {
        "week_start": week_start().isoformat(),
        "sections": [
            {"key": key, "title": title, "films": films[:SECTION_LIMIT]}
            for key, title, films in sections
            if films
        ],
        "total": sum(len(films[:SECTION_LIMIT]) for _key, _title, films in sections),
    }
