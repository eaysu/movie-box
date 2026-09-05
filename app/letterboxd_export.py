"""Safe, dependency-free parser for Letterboxd's official export ZIP."""

from __future__ import annotations

import csv
import io
import re
import unicodedata
import zipfile
from dataclasses import dataclass
from datetime import datetime


MAX_EXPORT_BYTES = 12 * 1024 * 1024
MAX_UNCOMPRESSED_BYTES = 24 * 1024 * 1024
MAX_FILMS = 50_000


class LetterboxdExportError(ValueError):
    pass


@dataclass(frozen=True)
class LetterboxdExport:
    watched: list[dict]
    watchlist: list[dict]


def _csv_rows(archive: zipfile.ZipFile, name: str) -> list[dict[str, str]]:
    try:
        with archive.open(name) as source:
            text = io.TextIOWrapper(source, encoding="utf-8-sig", newline="")
            return list(csv.DictReader(text))
    except KeyError:
        return []
    except (UnicodeDecodeError, csv.Error) as exc:
        raise LetterboxdExportError("Export içindeki CSV dosyası okunamadı.") from exc


def _year(value: str | None) -> int | None:
    try:
        year = int(str(value or "").strip())
    except (TypeError, ValueError):
        return None
    return year if 1870 <= year <= 2200 else None


def _rating(value: str | None) -> float | None:
    try:
        rating = float(str(value or "").strip())
    except (TypeError, ValueError):
        return None
    return rating if 0.5 <= rating <= 5.0 else None


def _slug(title: str, year: int | None) -> str:
    folded = unicodedata.normalize("NFKD", title).encode("ascii", "ignore").decode("ascii")
    base = re.sub(r"[^a-z0-9]+", "-", folded.lower()).strip("-")[:140]
    if not base:
        return ""
    # Letterboxd export exposes short URLs rather than public film slugs. This
    # stable title slug matches the normal Letterboxd slug for most films; a
    # year suffix only resolves genuine same-title collisions in one export.
    return base


def _date_rank(value: str | None) -> tuple[int, str]:
    raw = str(value or "").strip()
    try:
        return (1, datetime.strptime(raw, "%Y-%m-%d").date().isoformat())
    except ValueError:
        return (0, raw)


def _rows_to_films(rows: list[dict[str, str]], ratings: dict[tuple[str, str, int | None], float]) -> list[dict]:
    by_key: dict[tuple[str, str, int | None], dict] = {}
    for row in rows:
        title = str(row.get("Name") or "").strip()
        year = _year(row.get("Year"))
        uri = str(row.get("Letterboxd URI") or "").strip()
        if not title:
            continue
        key = (uri, title.casefold(), year)
        film = {
            "slug": _slug(title, year),
            "title": title[:300],
            "year": year,
            "user_rating": ratings.get(key),
            "date": str(row.get("Date") or "").strip(),
        }
        if not film["slug"]:
            continue
        previous = by_key.get(key)
        if previous is None or _date_rank(film["date"]) >= _date_rank(previous["date"]):
            by_key[key] = film

    films = sorted(by_key.values(), key=lambda film: _date_rank(film["date"]), reverse=True)
    # Same title/year can theoretically map to different Letterboxd entries.
    # Preserve both deterministically rather than letting the DB primary key
    # silently collapse one of them.
    seen: dict[str, int] = {}
    for film in films:
        base = film["slug"]
        seen[base] = seen.get(base, 0) + 1
        if seen[base] > 1:
            film["slug"] = f"{base}-{seen[base]}"
    return films[:MAX_FILMS]


def parse_letterboxd_export(payload: bytes) -> LetterboxdExport:
    if not payload:
        raise LetterboxdExportError("Bir Letterboxd export ZIP dosyası seç.")
    if len(payload) > MAX_EXPORT_BYTES:
        raise LetterboxdExportError("ZIP dosyası çok büyük.")
    try:
        archive = zipfile.ZipFile(io.BytesIO(payload))
    except zipfile.BadZipFile as exc:
        raise LetterboxdExportError("Geçerli bir Letterboxd export ZIP dosyası seç.") from exc
    with archive:
        infos = archive.infolist()
        if sum(info.file_size for info in infos) > MAX_UNCOMPRESSED_BYTES:
            raise LetterboxdExportError("ZIP içeriği güvenli sınırı aşıyor.")
        names = {info.filename for info in infos}
        if "watched.csv" not in names:
            raise LetterboxdExportError("ZIP içinde watched.csv bulunamadı.")
        ratings_rows = _csv_rows(archive, "ratings.csv")
        ratings = {
            (str(row.get("Letterboxd URI") or "").strip(), str(row.get("Name") or "").strip().casefold(), _year(row.get("Year"))): rating
            for row in ratings_rows
            if (rating := _rating(row.get("Rating"))) is not None
        }
        watched = _rows_to_films(_csv_rows(archive, "watched.csv"), ratings)
        watchlist = _rows_to_films(_csv_rows(archive, "watchlist.csv"), {})
    if not watched:
        raise LetterboxdExportError("Export içinde içe aktarılacak izlenmiş film bulunamadı.")
    return LetterboxdExport(watched=watched, watchlist=watchlist)
