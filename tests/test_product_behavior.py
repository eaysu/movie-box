import unittest
import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from app.auth import Account
from app.enrich import EnrichedFilm
from app.main import (
    _add_random_reasons,
    _personality_refresh_needed,
    _refresh_profile_watchlist,
)


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


if __name__ == "__main__":
    unittest.main()
