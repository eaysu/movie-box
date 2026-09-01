import unittest

from app.enrich import EnrichedFilm
from app.main import _add_random_reasons, _personality_refresh_needed


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


if __name__ == "__main__":
    unittest.main()
