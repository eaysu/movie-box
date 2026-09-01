import unittest
import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from app.auth import Account
from app.enrich import EnrichedFilm
from app.main import (
    _add_random_reasons,
    _check_profile_watchlist_freshness,
    _personality_refresh_needed,
    _refresh_profile_watchlist,
)
from app.scraper import ScrapedFilm


class ProductBehaviorTests(unittest.TestCase):
    def test_personality_stays_stable_when_fav4_is_unchanged(self):
        stored = {
            "taste": {"analysis": ["existing"], "personality": "keep me"},
            "favorite_films": [{"slug": "a"}, {"slug": "b"}],
        }
        current = [
            EnrichedFilm(title="A", slug="a"),
            EnrichedFilm(title="B", slug="b"),
        ]

        self.assertFalse(_personality_refresh_needed(stored, current))

    def test_personality_refreshes_when_fav4_changes(self):
        stored = {
            "taste": {"analysis": ["existing"], "personality": "old"},
            "favorite_films": [{"slug": "a"}, {"slug": "b"}],
        }
        current = [
            EnrichedFilm(title="A", slug="a"),
            EnrichedFilm(title="C", slug="c"),
        ]

        self.assertTrue(_personality_refresh_needed(stored, current))

    def test_random_pick_has_a_short_reason(self):
        film = EnrichedFilm(
            title="Surprise", slug="surprise", director="A Director"
        )

        _add_random_reasons([film], discover_fallback=False)

        self.assertIn("izleme listendeki", film.reason)
        self.assertIn("A Director", film.reason)

    def test_explicit_profile_refresh_bypasses_the_watchlist_cache(self):
        account = Account(
            id=1,
            auth_user_id="auth-1",
            username="film_fan",
            display_name="Film Fan",
        )
        settings = SimpleNamespace(
            has_tmdb=False,
            scrape_delay=0,
            scrape_max_pages=20,
            watchlist_film_limit=1000,
            scrape_max_retries=3,
        )
        load = AsyncMock(return_value=([EnrichedFilm(title="New", slug="new")], False))
        with (
            patch("app.main._make_cache", return_value=(None, object())),
            patch("app.main._make_persistent_cache", return_value=object()),
            patch("app.main._load_user_films", new=load),
        ):
            count = asyncio.run(
                _refresh_profile_watchlist(account, settings, SimpleNamespace())
            )

        self.assertEqual(count, 1)
        self.assertEqual(load.await_args.args[:2], ("film_fan", "watchlist"))
        self.assertTrue(load.await_args.kwargs["force"])

    def test_entry_watchlist_check_starts_full_refresh_when_head_changed(self):
        account = Account(
            id=1, auth_user_id="auth-1", username="film_fan", display_name="Film Fan"
        )
        settings = SimpleNamespace(
            has_tmdb=False,
            scrape_delay=0,
            scrape_max_pages=8,
            watchlist_film_limit=150,
            scrape_max_retries=3,
        )

        class FakeCache:
            def __init__(self):
                self.sets = []

            def get(self, namespace, _key, ttl=None):
                return None

            def get_with_freshness(self, namespace, _key, ttl=None):
                if namespace == "films_watchlist":
                    return ([{"slug": "old-film"}], True)
                return ({"complete": True}, True)

            def set(self, namespace, key, value):
                self.sets.append((namespace, key, value))

            def touch(self, *_args):
                raise AssertionError("changed watchlist must not be touched as current")

        start = AsyncMock(return_value=(object(), False))
        with (
            patch("app.main._make_cache", return_value=(None, object())),
            patch("app.main._make_persistent_cache", return_value=FakeCache()),
            patch(
                "app.main.scrape_watchlist",
                new=AsyncMock(return_value=([ScrapedFilm(title="New", year=None, slug="new-film")], True)),
            ),
            patch("app.main._get_or_create_film_flight", new=start),
        ):
            result = asyncio.run(
                _check_profile_watchlist_freshness(account, settings, SimpleNamespace())
            )

        self.assertEqual(result, {"status": "refreshing", "changed": True})
        self.assertEqual(start.await_args.args[:2], ("film_fan", "watchlist"))

    def test_entry_watchlist_check_touches_unchanged_cache(self):
        account = Account(
            id=1, auth_user_id="auth-1", username="film_fan", display_name="Film Fan"
        )
        settings = SimpleNamespace(scrape_max_retries=3)

        class FakeCache:
            def __init__(self):
                self.touches = []
                self.sets = []

            def get(self, namespace, _key, ttl=None):
                return None

            def get_with_freshness(self, namespace, _key, ttl=None):
                if namespace == "films_watchlist":
                    return ([{"slug": "same-film"}], True)
                return ({"complete": True}, True)

            def touch(self, namespace, key):
                self.touches.append((namespace, key))

            def set(self, namespace, key, value):
                self.sets.append((namespace, key, value))

        cache = FakeCache()
        with (
            patch("app.main._make_cache", return_value=(None, object())),
            patch("app.main._make_persistent_cache", return_value=cache),
            patch(
                "app.main.scrape_watchlist",
                new=AsyncMock(return_value=([ScrapedFilm(title="Same", year=None, slug="same-film")], True)),
            ),
            patch("app.main._get_or_create_film_flight", new=AsyncMock()) as start,
        ):
            result = asyncio.run(
                _check_profile_watchlist_freshness(account, settings, SimpleNamespace())
            )

        self.assertEqual(result, {"status": "current", "changed": False})
        self.assertEqual(cache.touches, [("films_watchlist", "film_fan")])
        self.assertEqual(
            cache.sets,
            [("watchlist_head_check", "film_fan", {"checked": True})],
        )
        start.assert_not_awaited()

    def test_entry_watchlist_check_is_deferred_during_persistent_cooldown(self):
        account = Account(
            id=1, auth_user_id="auth-1", username="film_fan", display_name="Film Fan"
        )
        settings = SimpleNamespace(scrape_max_retries=3)

        class FakeCache:
            def get(self, namespace, key, ttl=None):
                self.last_get = (namespace, key, ttl)
                return {"checked": True}

        cache = FakeCache()
        scrape = AsyncMock()
        with (
            patch("app.main._make_cache", return_value=(None, object())),
            patch("app.main._make_persistent_cache", return_value=cache),
            patch("app.main.scrape_watchlist", new=scrape),
        ):
            result = asyncio.run(
                _check_profile_watchlist_freshness(account, settings, SimpleNamespace())
            )

        self.assertEqual(result, {"status": "deferred", "changed": False})
        self.assertEqual(cache.last_get[:2], ("watchlist_head_check", "film_fan"))
        self.assertEqual(cache.last_get[2], 30 * 60)
        scrape.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
