import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from app.scraper import (
    MarkupChangedError,
    _fetch_profile_with_fresh_sessions,
    _parse_profile_page,
)


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


class ProfileRetryTests(unittest.IsolatedAsyncioTestCase):
    async def test_blocked_profile_retry_uses_a_fresh_browser_session(self):
        statuses = iter((403, 200))
        sessions = []

        class FakeSession:
            def __init__(self, *, impersonate):
                self.impersonate = impersonate
                self.profile_status = next(statuses)
                sessions.append(self)

            async def __aenter__(self):
                return self

            async def __aexit__(self, *_args):
                return None

            async def get(self, url, **_kwargs):
                status = 200 if url == "https://letterboxd.com/" else self.profile_status
                return SimpleNamespace(status_code=status, text="profile")

        with (
            patch("app.scraper.AsyncSession", FakeSession),
            patch("app.scraper._human_pause", new=AsyncMock()),
            patch("app.scraper.asyncio.sleep", new=AsyncMock()),
        ):
            response, status = await _fetch_profile_with_fresh_sessions(
                "sample_user", max_retries=2
            )

        self.assertEqual(status, 200)
        self.assertEqual(response.text, "profile")
        self.assertEqual(len(sessions), 2)
        self.assertNotEqual(sessions[0].impersonate, sessions[1].impersonate)


if __name__ == "__main__":
    unittest.main()
