import unittest

from app.enrich import EnrichedFilm
from app.recommender import rank_watchlist


class RatingAwareRankingTests(unittest.TestCase):
    def test_low_rating_is_negative_signal(self):
        watched = [
            EnrichedFilm(
                title="Loved Space Film",
                slug="loved-space",
                genres=["Science Fiction"],
                keywords=["space", "astronaut"],
                user_rating=5.0,
            ),
            EnrichedFilm(
                title="Disliked Slasher",
                slug="disliked-slasher",
                genres=["Horror"],
                keywords=["slasher", "gore"],
                user_rating=1.0,
            ),
        ]
        watchlist = [
            EnrichedFilm(
                title="Another Slasher",
                slug="another-slasher",
                genres=["Horror"],
                keywords=["slasher", "gore"],
            ),
            EnrichedFilm(
                title="Another Space Journey",
                slug="space-journey",
                genres=["Science Fiction"],
                keywords=["space", "astronaut"],
            ),
        ]

        ranked = rank_watchlist(watched, watchlist, n=2)

        self.assertEqual(ranked[0].slug, "space-journey")
        self.assertGreater(ranked[0].similarity, ranked[1].similarity)

    def test_mmr_avoids_near_duplicate_shortlist(self):
        watched = [
            EnrichedFilm(title="Space Love", genres=["Science Fiction"], keywords=["space"]),
            EnrichedFilm(title="Courtroom Love", genres=["Drama"], keywords=["courtroom"]),
        ]
        watchlist = [
            EnrichedFilm(title="Space One", slug="space-one", genres=["Science Fiction"], keywords=["space"]),
            EnrichedFilm(title="Space Two", slug="space-two", genres=["Science Fiction"], keywords=["space"]),
            EnrichedFilm(title="Courtroom", slug="courtroom", genres=["Drama"], keywords=["courtroom"]),
        ]

        ranked = rank_watchlist(watched, watchlist, n=2)

        self.assertEqual(len(ranked), 2)
        self.assertIn("courtroom", {film.slug for film in ranked})


if __name__ == "__main__":
    unittest.main()
