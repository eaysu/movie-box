import unittest
from unittest.mock import AsyncMock, patch

import httpx

from app.enrich import Enricher
from app.scraper import ScrapedFilm


class _Response:
    def __init__(self, status_code, payload=None, headers=None):
        self.status_code = status_code
        self._payload = payload or {}
        self.headers = headers or {}
        self.request = httpx.Request("GET", "https://api.themoviedb.org/test")

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise httpx.HTTPStatusError(
                "request failed", request=self.request, response=self
            )


class TmdbRetryTests(unittest.IsolatedAsyncioTestCase):
    async def test_429_honors_retry_after_then_succeeds(self):
        client = AsyncMock()
        client.get.side_effect = [
            _Response(429, headers={"Retry-After": "0"}),
            _Response(200, payload={"results": [{"id": 1}]}),
        ]
        enricher = Enricher("key", cache=None)

        with patch("app.enrich.asyncio.sleep", new=AsyncMock()) as sleep:
            payload = await enricher._get(client, "/search/movie", query="Perfect Days")

        self.assertEqual(payload["results"][0]["id"], 1)
        self.assertEqual(client.get.await_count, 2)
        sleep.assert_awaited_once_with(0.0)
        self.assertEqual(enricher._rate_limits, 1)


class TwoStageEnrichmentTests(unittest.IsolatedAsyncioTestCase):
    async def test_details_are_only_loaded_for_selected_films(self):
        class MemoryCache:
            def __init__(self):
                self.values = {}

            def get(self, namespace, key, ttl=None):
                return self.values.get((namespace, str(key)))

            def set(self, namespace, key, value):
                self.values[(namespace, str(key))] = value

        async def fake_get(_client, path, **_params):
            if path == "/search/movie":
                return {
                    "results": [{
                        "id": 42,
                        "title": "Perfect Days",
                        "release_date": "2023-01-01",
                        "genre_ids": [1],
                        "overview": "A quiet life in Tokyo.",
                        "vote_average": 7.8,
                        "poster_path": "/poster.jpg",
                    }]
                }
            return {
                "keywords": {"keywords": [{"name": "daily life"}]},
                "credits": {"crew": [{"job": "Director", "name": "Wim Wenders"}]},
            }

        enricher = Enricher("key", MemoryCache())
        enricher._genre_map = {1: "Drama"}
        enricher._get = AsyncMock(side_effect=fake_get)

        with patch("app.enrich._get_tmdb_client", new=AsyncMock(return_value=object())):
            films = await enricher.enrich(
                [ScrapedFilm(title="Perfect Days", year=2023, slug="perfect-days")],
                include_details=False,
            )
            self.assertEqual(enricher._get.await_count, 1)
            self.assertEqual(films[0].director, "")
            self.assertFalse(films[0].details_loaded)

            await enricher.ensure_details(films)
            self.assertEqual(enricher._get.await_count, 2)
            self.assertEqual(films[0].director, "Wim Wenders")
            self.assertEqual(films[0].keywords, ["daily life"])
            self.assertTrue(films[0].details_loaded)

            await enricher.ensure_details(films)
            self.assertEqual(enricher._get.await_count, 2)


class SharedAssetTests(unittest.IsolatedAsyncioTestCase):
    async def test_poster_and_director_cache_hits_skip_tmdb(self):
        class MemoryCache:
            def __init__(self):
                self.values = {}

            def get(self, namespace, key, ttl=None):
                return self.values.get((namespace, str(key)))

            def set(self, namespace, key, value):
                self.values[(namespace, str(key))] = value

        class Assets:
            def get_film_posters_by_tmdb_ids(self, _ids):
                return {42: "https://image.tmdb.org/t/p/w500/shared.jpg"}

            def get_director_images(self, _names):
                return {"Wim Wenders": "https://image.tmdb.org/t/p/w185/wim.jpg"}

        enricher = Enricher("key", MemoryCache(), asset_store=Assets())
        enricher._get = AsyncMock(side_effect=AssertionError("TMDb should not run"))
        with patch("app.enrich._get_tmdb_client", new=AsyncMock(return_value=object())):
            posters = await enricher.posters_by_id([42])
            people = await enricher.person_photos(["Wim Wenders"])

        self.assertEqual(posters[42], "https://image.tmdb.org/t/p/w500/shared.jpg")
        self.assertEqual(people["Wim Wenders"], "https://image.tmdb.org/t/p/w185/wim.jpg")
        enricher._get.assert_not_awaited()

    async def test_shared_slug_asset_skips_movie_search_for_search_only_pass(self):
        class MemoryCache:
            def get(self, _namespace, _key, ttl=None):
                return None

            def set(self, _namespace, _key, _value):
                return None

        class Assets:
            def get_film_assets(self, _slugs):
                return {
                    "perfect-days": {
                        "film_slug": "perfect-days",
                        "title": "Perfect Days",
                        "release_year": 2023,
                        "tmdb_id": 976893,
                        "poster_url": "https://image.tmdb.org/t/p/w500/perfect.jpg",
                    }
                }

        enricher = Enricher("key", MemoryCache(), asset_store=Assets())
        enricher._get = AsyncMock(side_effect=AssertionError("TMDb should not run"))
        with patch("app.enrich._get_tmdb_client", new=AsyncMock(return_value=object())):
            films = await enricher.enrich(
                [ScrapedFilm(title="Perfect Days", year=2023, slug="perfect-days")],
                include_details=False,
            )

        self.assertEqual(films[0].tmdb_id, 976893)
        self.assertEqual(
            films[0].poster_url,
            "https://image.tmdb.org/t/p/w500/perfect.jpg",
        )
        enricher._get.assert_not_awaited()

    async def test_complete_shared_catalog_record_skips_search_and_details(self):
        class MemoryCache:
            def get(self, _namespace, _key, ttl=None):
                return None

            def set(self, _namespace, _key, _value):
                return None

        class Assets:
            def get_film_assets(self, _slugs):
                return {
                    "perfect-days": {
                        "film_slug": "perfect-days",
                        "title": "Perfect Days",
                        "release_year": 2023,
                        "tmdb_id": 976893,
                        "poster_url": "https://image.tmdb.org/t/p/w500/perfect.jpg",
                        "overview": "A quiet life in Tokyo.",
                        "director": "Wim Wenders",
                        "genres": ["Drama"],
                        "keywords": ["tokyo"],
                        "vote_average": 7.8,
                        "matched": True,
                        "details_loaded": True,
                    }
                }

            def save_film_posters(self, _rows):
                return 1

        enricher = Enricher("key", MemoryCache(), asset_store=Assets())
        enricher._get = AsyncMock(side_effect=AssertionError("TMDb should not run"))
        with patch("app.enrich._get_tmdb_client", new=AsyncMock(return_value=object())):
            films = await enricher.enrich(
                [ScrapedFilm(title="Perfect Days", year=2023, slug="perfect-days")],
                include_details=True,
            )

        self.assertEqual(films[0].director, "Wim Wenders")
        self.assertEqual(films[0].overview, "A quiet life in Tokyo.")
        self.assertTrue(films[0].details_loaded)
        enricher._get.assert_not_awaited()

    async def test_poster_only_l1_hit_does_not_block_metadata_completion(self):
        class MemoryCache:
            def __init__(self):
                self.values = {
                    ("tmdb", "perfect-days"): {
                        "title": "Perfect Days",
                        "year": 2023,
                        "slug": "perfect-days",
                        "poster_url": "https://letterboxd.example/poster.jpg",
                        "details_loaded": False,
                    }
                }

            def get(self, namespace, key, ttl=None):
                return self.values.get((namespace, str(key)))

            def set(self, namespace, key, value):
                self.values[(namespace, str(key))] = value

        async def fake_get(_client, path, **_params):
            if path == "/search/movie":
                return {
                    "results": [{
                        "id": 976893,
                        "title": "Perfect Days",
                        "release_date": "2023-01-01",
                        "genre_ids": [1],
                        "overview": "A quiet life in Tokyo.",
                        "vote_average": 7.8,
                        "poster_path": None,
                    }]
                }
            self.assertEqual(path, "/movie/976893")
            return {
                "overview": "A quiet life in Tokyo.",
                "genres": [{"name": "Drama"}],
                "keywords": {"keywords": [{"name": "daily life"}]},
                "credits": {"crew": [{"job": "Director", "name": "Wim Wenders"}]},
            }

        enricher = Enricher("key", MemoryCache())
        enricher._genre_map = {1: "Drama"}
        enricher._get = AsyncMock(side_effect=fake_get)
        with patch("app.enrich._get_tmdb_client", new=AsyncMock(return_value=object())):
            films = await enricher.enrich(
                [ScrapedFilm(title="Perfect Days", year=2023, slug="perfect-days")],
                include_details=True,
            )

        self.assertEqual(films[0].tmdb_id, 976893)
        self.assertEqual(films[0].overview, "A quiet life in Tokyo.")
        self.assertEqual(films[0].director, "Wim Wenders")
        self.assertEqual(
            films[0].poster_url, "https://letterboxd.example/poster.jpg"
        )
        self.assertTrue(films[0].details_loaded)
        self.assertEqual(enricher._get.await_count, 2)

    async def test_director_filmography_uses_shared_person_id_and_durable_cache(self):
        class MemoryCache:
            def __init__(self):
                self.values = {}

            def get(self, namespace, key, ttl=None):
                return self.values.get((namespace, str(key)))

            def set(self, namespace, key, value):
                self.values[(namespace, str(key))] = value

        class Assets:
            def get_director_assets(self, _names):
                return {
                    "Wim Wenders": {
                        "tmdb_person_id": 36,
                        "photo_url": "https://image.tmdb.org/t/p/w185/wim.jpg",
                    }
                }

            def save_director_images(self, _rows):
                return 1

        async def fake_get(_client, path, **_params):
            self.assertEqual(path, "/person/36/movie_credits")
            return {
                "crew": [
                    {"id": 976893, "job": "Director"},
                    {"id": 123, "job": "Producer"},
                ]
            }

        enricher = Enricher("key", MemoryCache(), asset_store=Assets())
        enricher._get = AsyncMock(side_effect=fake_get)
        with patch("app.enrich._get_tmdb_client", new=AsyncMock(return_value=object())):
            first = await enricher.director_movie_ids(["Wim Wenders"])
            second = await enricher.director_movie_ids(["Wim Wenders"])

        self.assertEqual(first["Wim Wenders"], {976893})
        self.assertEqual(second["Wim Wenders"], {976893})
        self.assertEqual(enricher._get.await_count, 1)


if __name__ == "__main__":
    unittest.main()
