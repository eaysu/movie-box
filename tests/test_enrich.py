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


if __name__ == "__main__":
    unittest.main()
