import unittest

from app.enrich import EnrichedFilm
from app.scraper import ScrapedFilm, ScrapedProfile
from app.taste_profile import build_taste_profile, taste_source_fingerprint


class TasteProfileTests(unittest.TestCase):
    def test_favorite_director_prefers_explicitly_loved_films(self):
        watched = [
            EnrichedFilm(
                title="Loved One",
                director="Loved Director",
                genres=["Drama"],
                keywords=["memory"],
                user_rating=5.0,
            ),
            EnrichedFilm(
                title="Loved Two",
                director="Loved Director",
                genres=["Drama"],
                user_rating=4.5,
            ),
            EnrichedFilm(
                title="Disliked One",
                director="Frequent But Disliked",
                genres=["Horror"],
                user_rating=1.0,
            ),
            EnrichedFilm(
                title="Disliked Two",
                director="Frequent But Disliked",
                genres=["Horror"],
                user_rating=1.5,
            ),
            EnrichedFilm(
                title="Disliked Three",
                director="Frequent But Disliked",
                genres=["Horror"],
                user_rating=2.0,
            ),
        ]

        profile = build_taste_profile(watched)

        self.assertEqual(profile.favorite_director, "Loved Director")
        self.assertEqual(profile.top_genres[0], "Drama")
        self.assertIn("Loved Director", profile.summary)
        self.assertEqual(profile.rated_count, 5)

    def test_unrated_profile_uses_frequency_and_reports_low_confidence(self):
        watched = [
            EnrichedFilm(title=f"Film {index}", director="Same Director")
            for index in range(3)
        ]

        profile = build_taste_profile(watched)

        self.assertEqual(profile.favorite_director, "Same Director")
        self.assertEqual(profile.confidence_level, "low")
        self.assertEqual(profile.sample_size, 3)

    def test_empty_profile_is_valid(self):
        profile = build_taste_profile([])

        self.assertEqual(profile.sample_size, 0)
        self.assertEqual(profile.confidence_score, 0)

    def test_source_fingerprint_changes_with_rating(self):
        profile = ScrapedProfile(
            username="film_fan",
            display_name="Film Fan",
            avatar_url="https://example.com/avatar.jpg",
            bio="",
            favorite_films=[ScrapedFilm("Favorite", 2001, "favorite")],
        )
        watched = [
            EnrichedFilm(title="Watched", slug="watched", user_rating=4.0)
        ]
        first = taste_source_fingerprint(profile, watched)
        self.assertEqual(first, taste_source_fingerprint(profile, watched))

        watched[0].user_rating = 4.5
        self.assertNotEqual(first, taste_source_fingerprint(profile, watched))


if __name__ == "__main__":
    unittest.main()
