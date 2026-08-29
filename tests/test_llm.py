import unittest

from app.enrich import EnrichedFilm
from app.llm import _build_prompt


class LlmTasteContextTests(unittest.TestCase):
    def test_prompt_includes_only_explicitly_liked_rated_films(self):
        watched = [
            EnrichedFilm(title="Loved Film", user_rating=4.5),
            EnrichedFilm(title="Disliked Film", user_rating=1.5),
            EnrichedFilm(title="Unrated Film"),
        ]
        candidates = [EnrichedFilm(title="Candidate", year=2024)]

        prompt = _build_prompt(watched, candidates, 1)

        self.assertIn("Loved Film", prompt)
        self.assertIn("4.5/5", prompt)
        self.assertNotIn("Disliked Film", prompt)
        self.assertNotIn("Unrated Film", prompt)

    def test_unrated_profile_is_labeled_as_implicit_history(self):
        prompt = _build_prompt(
            [EnrichedFilm(title="Recent Film")],
            [EnrichedFilm(title="Candidate")],
            1,
        )

        self.assertIn("Puan verisi olmadığı için", prompt)
        self.assertIn("Recent Film", prompt)


if __name__ == "__main__":
    unittest.main()
