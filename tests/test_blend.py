import unittest

from app.enrich import EnrichedFilm
from app.main import _calculate_blend


def _profile(prefix: str, *, shared_features: bool, count: int = 100):
    return [
        EnrichedFilm(
            title=f"{prefix} {index}",
            slug=f"{prefix}-{index}",
            year=2020 if shared_features else (1980 if prefix == "first" else 2000),
            genres=["Drama"] if shared_features else [f"Genre {prefix}"],
            keywords=["identity"] if shared_features else [f"keyword {prefix}"],
            director="Shared Director" if shared_features else f"Director {prefix}",
        )
        for index in range(count)
    ]


class BlendCalibrationTests(unittest.TestCase):
    def test_identical_feature_profiles_score_high_with_high_confidence(self):
        first = _profile("first", shared_features=True)
        second = _profile("second", shared_features=True)

        result = _calculate_blend(first, second)

        self.assertEqual(result["score"], 100)
        self.assertEqual(result["confidence"]["level"], "high")

    def test_disjoint_profiles_can_score_zero_instead_of_artificial_seventy(self):
        first = _profile("first", shared_features=False)
        second = _profile("second", shared_features=False)

        result = _calculate_blend(first, second)

        self.assertEqual(result["score"], 0)
        self.assertEqual(result["confidence"]["level"], "high")

    def test_small_profiles_report_low_confidence(self):
        first = _profile("first", shared_features=True, count=5)
        second = _profile("second", shared_features=True, count=5)

        result = _calculate_blend(first, second)

        self.assertEqual(result["confidence"]["level"], "low")
        self.assertEqual(result["confidence"]["sample_size"], 5)


if __name__ == "__main__":
    unittest.main()
