import csv
import io
import zipfile

import pytest

from app.letterboxd_export import LetterboxdExportError, parse_letterboxd_export


def _export(**files: str) -> bytes:
    data = io.BytesIO()
    with zipfile.ZipFile(data, "w") as archive:
        for name, value in files.items():
            archive.writestr(name, value)
    return data.getvalue()


def test_export_imports_watched_ratings_and_watchlist_in_recent_order():
    payload = _export(
        **{
            "watched.csv": "Date,Name,Year,Letterboxd URI\n2024-01-01,Old Film,1999,https://boxd.it/old\n2024-02-01,New Film,2024,https://boxd.it/new\n",
            "ratings.csv": "Date,Name,Year,Letterboxd URI,Rating\n2024-02-01,New Film,2024,https://boxd.it/new,4.5\n",
            "watchlist.csv": "Date,Name,Year,Letterboxd URI\n2024-03-01,Next Film,2025,https://boxd.it/next\n",
        }
    )

    result = parse_letterboxd_export(payload)

    assert [film["title"] for film in result.watched] == ["New Film", "Old Film"]
    assert result.watched[0]["user_rating"] == 4.5
    assert result.watchlist == [{"slug": "next-film", "title": "Next Film", "year": 2025, "user_rating": None, "date": "2024-03-01"}]


def test_export_requires_watched_csv():
    with pytest.raises(LetterboxdExportError, match="watched.csv"):
        parse_letterboxd_export(_export(**{"watchlist.csv": "Date,Name\n"}))
