import unittest

from app.enrich import EnrichedFilm
from app.semantic import profile_similarity, taste_document_scores, weighted_profile_scores


class LocalSemanticLayerTests(unittest.TestCase):
    def test_synopsis_layer_scores_thematically_related_candidate(self):
        watched = [
            EnrichedFilm(
                title="Memory", overview="A family confronts grief and memory after a loss.",
                keywords=["family", "grief"],
            ),
            EnrichedFilm(
                title="Home", overview="Two siblings return home to face a difficult past.",
                keywords=["home", "siblings"],
            ),
            EnrichedFilm(
                title="Distance", overview="A quiet relationship changes across several years.",
                keywords=["relationship"],
            ),
        ]
        candidates = [
            EnrichedFilm(
                title="Return", overview="A family returns home and revisits a painful memory.",
                keywords=["family", "memory"],
            ),
            EnrichedFilm(
                title="Orbit", overview="Astronauts attempt a dangerous mission beyond Earth.",
                keywords=["space"],
            ),
        ]

        scores, coverage = weighted_profile_scores(
            watched, candidates, positive_weights=[1, 1, 1], negative_weights=[0, 0, 0]
        )

        self.assertGreaterEqual(coverage, 1.0)
        self.assertIsNotNone(scores)
        self.assertGreater(scores[0], scores[1])

    def test_profile_similarity_is_disabled_without_synopses(self):
        films = [EnrichedFilm(title="One", keywords=["memory"])] * 3
        score, coverage = profile_similarity(
            films, films, first_weights=[1, 1, 1], second_weights=[1, 1, 1]
        )

        self.assertEqual(coverage, 0.0)
        self.assertIsNone(score)

    def test_directory_documents_produce_one_score_per_candidate(self):
        scores, coverage = taste_document_scores(
            {"top_keywords": ["memory", "family"], "top_genres": ["Drama"]},
            [
                {"top_keywords": ["family", "grief"], "top_genres": ["Drama"]},
                {"top_keywords": ["spaceship", "alien"], "top_genres": ["Science Fiction"]},
                {"top_keywords": ["memory", "loss"], "top_genres": ["Drama"]},
            ],
        )

        self.assertEqual(len(scores), 3)
        self.assertGreater(coverage, 0.0)
        self.assertGreater(scores[0], scores[1])
