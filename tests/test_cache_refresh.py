import asyncio
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from app.cache import Cache, LayeredCache
from app.enrich import EnrichedFilm
from app import main
from app.main import _capacity_stream, _load_user_films
from app.scraper import ScrapedFilm


class CacheFreshnessTests(unittest.TestCase):
    def test_expired_value_remains_available_with_freshness_flag(self):
        with tempfile.TemporaryDirectory() as tmp:
            cache = Cache(Path(tmp) / "cache.sqlite3")
            with patch("app.cache.time.time", return_value=100.0):
                cache.set("films_watched", "film_fan", [{"slug": "old"}])

            with patch("app.cache.time.time", return_value=200.0):
                self.assertIsNone(cache.get("films_watched", "film_fan", ttl=50))
                value, fresh = cache.get_with_freshness(
                    "films_watched", "film_fan", ttl=50
                )

            self.assertFalse(fresh)
            self.assertEqual(value[0]["slug"], "old")


class LayeredCacheTests(unittest.TestCase):
    def test_prefetch_and_flush_batch_remote_operations(self):
        class RemoteCache:
            def __init__(self):
                self.values = {
                    ("tmdb", "film-a"): {"title": "Film A"},
                    ("tmdb", "film-b"): {"title": "Film B"},
                }
                self.read_batches = []
                self.write_batches = []

            def get(self, namespace, key, ttl=None):
                return self.values.get((namespace, key))

            def get_many(self, namespace, keys, ttl=None):
                self.read_batches.append((namespace, list(keys), ttl))
                return {
                    key: self.values[(namespace, key)]
                    for key in keys
                    if (namespace, key) in self.values
                }

            def set_many(self, namespace, values):
                self.write_batches.append((namespace, dict(values)))
                for key, value in values.items():
                    self.values[(namespace, key)] = value

        with tempfile.TemporaryDirectory() as tmp:
            local = Cache(Path(tmp) / "cache.sqlite3")
            remote = RemoteCache()
            cache = LayeredCache(local, remote)

            hydrated = cache.prefetch(
                "tmdb", ["film-a", "film-b", "missing"], ttl=60
            )
            self.assertEqual(hydrated, 2)
            self.assertEqual(len(remote.read_batches), 1)
            self.assertEqual(cache.get("tmdb", "film-a", ttl=60)["title"], "Film A")

            cache.set("tmdb", "film-c", {"title": "Film C"})
            cache.set("tmdb", "film-d", {"title": "Film D"})
            self.assertEqual(remote.write_batches, [])
            self.assertEqual(cache.flush(), 2)
            self.assertEqual(len(remote.write_batches), 1)
            self.assertEqual(
                set(remote.write_batches[0][1]), {"film-c", "film-d"}
            )

    def test_failed_remote_flush_is_retried(self):
        class FlakyRemote:
            def __init__(self):
                self.fail = True
                self.calls = 0

            def set_many(self, _namespace, _values):
                self.calls += 1
                if self.fail:
                    return False
                return True

        with tempfile.TemporaryDirectory() as tmp:
            remote = FlakyRemote()
            cache = LayeredCache(Cache(Path(tmp) / "cache.sqlite3"), remote)
            cache.set("tmdb", "film", {"title": "Film"})

            self.assertEqual(cache.flush(), 0)
            remote.fail = False
            self.assertEqual(cache.flush(), 1)
            self.assertEqual(remote.calls, 2)


class StaleWhileRevalidateTests(unittest.IsolatedAsyncioTestCase):
    async def test_stale_result_returns_before_background_refresh_finishes(self):
        stale = EnrichedFilm(title="Old Film", year=2000, slug="old-film").to_dict()

        class StaleCache:
            def __init__(self):
                self.writes = []

            def get_with_freshness(self, *_args, **_kwargs):
                return [stale], False

            def set(self, _namespace, _key, value):
                self.writes.append(value)

        cache = StaleCache()

        async def fake_scrape(_username, **_kwargs):
            await asyncio.sleep(0.03)
            return [ScrapedFilm(title="New Film", year=2024, slug="new-film")], True

        with patch("app.main.scrape_watched", side_effect=fake_scrape):
            films, from_cache = await _load_user_films(
                "stale_user",
                "watched",
                settings=None,
                enricher=None,
                pcache=cache,
                scrape_kwargs={},
            )
            self.assertTrue(from_cache)
            self.assertEqual(films[0].slug, "old-film")
            self.assertEqual(cache.writes, [])

            for _ in range(20):
                if cache.writes:
                    break
                await asyncio.sleep(0.01)

        self.assertEqual(cache.writes[0][0]["slug"], "new-film")

    async def test_incomplete_refresh_does_not_replace_stale_value(self):
        stale = EnrichedFilm(title="Old Film", year=2000, slug="old-film").to_dict()

        class StaleCache:
            def __init__(self):
                self.writes = []

            def get_with_freshness(self, *_args, **_kwargs):
                return [stale], False

            def set(self, *_args):
                self.writes.append(_args)

        cache = StaleCache()

        async def incomplete_scrape(_username, **_kwargs):
            return [ScrapedFilm(title="Partial", year=2024, slug="partial")], False

        with patch("app.main.scrape_watched", side_effect=incomplete_scrape):
            films, _ = await _load_user_films(
                "partial_user",
                "watched",
                settings=None,
                enricher=None,
                pcache=cache,
                scrape_kwargs={},
            )
            await asyncio.sleep(0.01)

        self.assertEqual(films[0].slug, "old-film")
        self.assertEqual(cache.writes, [])

    async def test_unchanged_head_fingerprint_skips_full_scrape(self):
        stale = [
            EnrichedFilm(title=f"Film {i}", year=2000 + i, slug=f"film-{i}").to_dict()
            for i in range(3)
        ]

        class FingerprintCache:
            def __init__(self):
                self.touches = []

            def get_with_freshness(self, namespace, *_args, **_kwargs):
                if namespace == "films_full_refresh":
                    return {"complete": True}, True
                return stale, False

            def touch(self, namespace, key):
                self.touches.append((namespace, key))
                return True

            def set(self, *_args):
                raise AssertionError("unchanged fingerprint must not rewrite cache")

        cache = FingerprintCache()
        head = [
            ScrapedFilm(title=f"Film {i}", year=2000 + i, slug=f"film-{i}")
            for i in range(3)
        ]

        with (
            patch("app.main.scrape_diary", return_value=(head, True)) as diary,
            patch("app.main.scrape_watched", new=AsyncMock()) as full_scrape,
        ):
            films, _ = await _load_user_films(
                "finger_user",
                "watched",
                settings=None,
                enricher=None,
                pcache=cache,
                scrape_kwargs={"max_retries": 1},
            )
            for _ in range(20):
                if cache.touches:
                    break
                await asyncio.sleep(0.01)

        self.assertEqual([film.slug for film in films], ["film-0", "film-1", "film-2"])
        diary.assert_awaited_once()
        full_scrape.assert_not_awaited()
        self.assertEqual(cache.touches, [("films_watched", "finger_user")])


class CapacityStreamTests(unittest.IsolatedAsyncioTestCase):
    async def test_second_stream_is_queued_until_first_releases_capacity(self):
        original = (main._sem, main._q_lock, main._q_waiting, main._q_active)
        main._sem = asyncio.Semaphore(1)
        main._q_lock = asyncio.Lock()
        main._q_waiting = 0
        main._q_active = 0
        release = asyncio.Event()
        started = asyncio.Event()

        async def slow_stream():
            started.set()
            await release.wait()
            yield "first-result"

        async def fast_stream():
            yield "second-result"

        first = _capacity_stream(slow_stream())
        first_event_task = asyncio.create_task(anext(first))
        await started.wait()

        second = _capacity_stream(fast_stream())
        queued = await anext(second)
        self.assertIn('"type": "queued"', queued)
        self.assertEqual(main._q_active, 1)

        release.set()
        self.assertEqual(await first_event_task, "first-result")
        await first.aclose()
        self.assertEqual(await anext(second), "second-result")
        await second.aclose()

        self.assertEqual((main._q_waiting, main._q_active), (0, 0))
        main._sem, main._q_lock, main._q_waiting, main._q_active = original


if __name__ == "__main__":
    unittest.main()
