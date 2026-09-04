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
def _film_card(row: dict, extra: dict | None = None) -> dict:
    card = {
        "title": row.get("title_raw") or row.get("title") or "",
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


def build_digest(screenings: list[dict], watched: list[dict], watchlist_slugs, taste) -> dict:
    """Shape one member's week from rows already in the database.

    Sections are ordered by how directly they can be acted on: something you
    already wanted to see, then something you loved that is back, then a new
    release that fits. An empty section is omitted, never padded.
    """
    wanted = {slug for slug in (watchlist_slugs or []) if slug}
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
                first_seen = str(seen.get("first_seen_at") or "")[:4]
                back_on_screen.append(_film_card(row, {
                    "slug": slug or seen.get("film_slug") or "",
                    "note": (
                        f"{first_seen}'de {float(rating):.1f} vermiştin"
                        if first_seen.isdigit() else f"{float(rating):.1f} vermiştin"
                    ),
                    "user_rating": float(rating),
                }))
            continue
        if slug and slug in wanted:
            on_watchlist.append(_film_card(row, {"note": "İzleme listende"}))
            continue
        director = str(row.get("director") or "").lower()
        row_genres = {str(genre).lower() for genre in (row.get("genres") or [])}
        if director and director in directors:
            fits_taste.append(_film_card(row, {"note": f"{row.get('director')} filmi"}))
        elif row_genres & genres:
            match = sorted(row_genres & genres)[0].title()
            fits_taste.append(_film_card(row, {"note": f"{match} tarafında"}))

    sections = [
        ("watchlist", "İzleme listende ve perdede", on_watchlist),
        ("back", "Tekrar perdede", back_on_screen),
        ("taste", "Zevkine uyan yeni vizyon", fits_taste),
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
