import unittest
from pathlib import Path

from app.scraper import MarkupChangedError, _parse_profile_page


FIXTURE = Path(__file__).parent / "fixtures" / "profile_public.html"


class ProfileParserTests(unittest.TestCase):
    def test_parses_avatar_identity_bio_and_ordered_favorite_four(self):
        profile = _parse_profile_page("sample_user", FIXTURE.read_text())

        self.assertEqual(profile.username, "sample_user")
        self.assertEqual(profile.display_name, "Sample User")
        self.assertEqual(
            profile.avatar_url,
            "https://a.ltrbxd.com/resized/avatar/sample-large.jpg",
        )
        self.assertEqual(profile.bio, "slow cinema & impossible romances")
        self.assertEqual(
            [film.slug for film in profile.favorite_films],
            ["first-film", "second-film", "third-film", "fourth-film"],
        )
        self.assertEqual(profile.favorite_films[0].year, 2001)
        self.assertIsNone(profile.favorite_films[0].poster_url)

    def test_missing_profile_summary_is_classified_as_markup_change(self):
        with self.assertRaises(MarkupChangedError):
            _parse_profile_page("sample_user", "<main>redesigned profile</main>")


if __name__ == "__main__":
    unittest.main()
