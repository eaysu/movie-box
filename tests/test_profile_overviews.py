import asyncio
from types import SimpleNamespace
from unittest.mock import Mock, patch

from app.enrich import EnrichedFilm
from app.main import _fill_overviews


def _settings():
    return SimpleNamespace(has_tmdb=True, tmdb_api_key="test-key")


def test_profile_overviews_use_shared_catalog_for_every_visible_film():
    rows = [
        {"slug": f"film-{index}", "title": f"Film {index}", "year": 2000 + index}
        for index in range(10)
    ]
    service = SimpleNamespace(
        get_film_assets=Mock(
            return_value={
                row["slug"]: {
                    "overview": f"Catalog overview {index}",
                    "poster_url": f"poster-{index}",
                    "director": f"Director {index}",
                    "tmdb_id": index + 1,
                }
                for index, row in enumerate(rows)
            }
        ),
        save_film_posters=Mock(return_value=10),
    )

    class NoExternalCalls:
        def __init__(self, *_args, **_kwargs):
            pass

        async def movie_meta_by_id(self, _ids):
            raise AssertionError("catalog hits must not call TMDb")

        async def enrich(self, *_args, **_kwargs):
            raise AssertionError("catalog hits must not call TMDb search")

    with (
        patch("app.main.get_settings", return_value=_settings()),
        patch("app.main._make_cache", return_value=(None, object())),
        patch("app.main.Enricher", NoExternalCalls),
    ):
        asyncio.run(_fill_overviews(service, rows, 10))

    assert [row["overview"] for row in rows] == [
        f"Catalog overview {index}" for index in range(10)
    ]
    assert service.get_film_assets.call_args.args[0] == [
        f"film-{index}" for index in range(10)
    ]


def test_profile_overview_prefers_exact_tmdb_id_before_title_search():
    rows = [
        {"slug": "known", "title": "Known", "year": 1999, "tmdb_id": 42},
        {"slug": "search", "title": "Search", "year": 2007},
    ]
    service = SimpleNamespace(
        get_film_assets=Mock(return_value={}),
        save_film_posters=Mock(return_value=2),
    )

    class FakeEnricher:
        def __init__(self, *_args, **_kwargs):
            self.searched = []

        async def movie_meta_by_id(self, ids):
            assert ids == [42]
            return {42: {"overview": "Exact id overview", "poster_url": "exact-poster"}}

        async def enrich(self, films, *, include_details=True):
            assert include_details is True
            assert films == [{"title": "Search", "year": 2007, "slug": "search"}]
            return [
                EnrichedFilm(
                    title="Search",
                    year=2007,
                    slug="search",
                    tmdb_id=84,
                    overview="Search overview",
                    poster_url="search-poster",
                    matched=True,
                    details_loaded=True,
                )
            ]

    with (
        patch("app.main.get_settings", return_value=_settings()),
        patch("app.main._make_cache", return_value=(None, object())),
        patch("app.main.Enricher", FakeEnricher),
    ):
        asyncio.run(_fill_overviews(service, rows, 2))

    assert rows[0]["overview"] == "Exact id overview"
    assert rows[1]["overview"] == "Search overview"
    assert rows[1]["tmdb_id"] == 84
    persisted = service.save_film_posters.call_args.args[0]
    assert {row["slug"] for row in persisted} == {"known", "search"}
