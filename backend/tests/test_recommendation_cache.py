import unittest

from app.enrich import EnrichedFilm
from app.main import _recommendation_cache_key


class RecommendationCacheKeyTests(unittest.TestCase):
    def test_key_is_stable_for_identical_profile(self):
        watched = [EnrichedFilm(title="A", slug="a", user_rating=4.5)]
        watchlist = [EnrichedFilm(title="B", slug="b")]

        first = _recommendation_cache_key(
            "film_fan", watched, watchlist, model="model-a", count=5
        )
        second = _recommendation_cache_key(
            "film_fan", watched, watchlist, model="model-a", count=5
        )
        self.assertEqual(first, second)

    def test_profile_rating_model_and_count_invalidate_key(self):
        base_watched = [EnrichedFilm(title="A", slug="a", user_rating=4.5)]
        changed_rating = [EnrichedFilm(title="A", slug="a", user_rating=2.0)]
        watchlist = [EnrichedFilm(title="B", slug="b")]
        base = _recommendation_cache_key(
            "film_fan", base_watched, watchlist, model="model-a", count=5
        )

        variants = (
            _recommendation_cache_key(
                "film_fan", changed_rating, watchlist, model="model-a", count=5
            ),
            _recommendation_cache_key(
                "film_fan", base_watched, watchlist, model="model-b", count=5
            ),
            _recommendation_cache_key(
                "film_fan", base_watched, watchlist, model="model-a", count=8
            ),
            _recommendation_cache_key(
                "film_fan", base_watched, [EnrichedFilm(title="C", slug="c")],
                model="model-a", count=5
            ),
        )
        self.assertTrue(all(key != base for key in variants))


if __name__ == "__main__":
    unittest.main()
