import asyncio
import unittest

from app.enrich import EnrichedFilm
from app.main import _blend_bridge_films, _calculate_blend


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


def _film(title, *, year=2021, genres=("Drama",), director="Someone"):
    slug = title.lower().replace(" ", "-")
    return EnrichedFilm(
        title=title,
        slug=slug,
        year=year,
        genres=list(genres),
        keywords=["identity"],
        director=director,
    )


class BlendBridgeFilmTests(unittest.TestCase):
    def test_bridge_pool_from_watchlists_excludes_films_either_user_saw(self):
        watched1 = [_film("Seen A"), _film("Seen B")]
        watched2 = [_film("Seen C")]
        watchlist1 = [_film("Bridge 1"), _film("Seen C"), _film("Bridge 2")]
        watchlist2 = [_film("Bridge 3"), _film("Seen A"), _film("Bridge 4"), _film("Bridge 5")]

        bridge = asyncio.run(
            _blend_bridge_films(watched1, watched2, watchlist1, watchlist2, n=5)
        )

        titles = {f.title for f in bridge}
        self.assertLessEqual(len(bridge), 5)
        self.assertNotIn("Seen A", titles)
        self.assertNotIn("Seen C", titles)
        self.assertTrue(titles.issubset({f"Bridge {i}" for i in range(1, 6)}))

    def test_bridge_dedupes_across_the_two_watchlists(self):
        watched1 = [_film("Seen A")]
        watched2 = [_film("Seen B")]
        shared = _film("Bridge Shared")
        watchlist1 = [shared, _film("Bridge X")]
        watchlist2 = [_film("bridge shared".title()), _film("Bridge Y")]

        bridge = asyncio.run(
            _blend_bridge_films(watched1, watched2, watchlist1, watchlist2, n=5)
        )

        titles = [f.title for f in bridge]
        self.assertEqual(len(titles), len(set(titles)))

    def test_bridge_returns_empty_without_candidates_or_enricher(self):
        bridge = asyncio.run(
            _blend_bridge_films([_film("Seen A")], [_film("Seen B")], [], [], n=5)
        )
        self.assertEqual(bridge, [])

    def test_bridge_widens_with_discover_pool_and_assigns_slugs(self):
        class _FakeEnricher:
            async def discover_pool(self, *, genre_names=None, limit=50):
                # Discover results arrive without a Letterboxd slug.
                return [
                    EnrichedFilm(title="The Prophecy", year=1995, slug="",
                                 genres=["Horror"], poster_url="p"),
                    EnrichedFilm(title="Carriers", year=2009, slug="",
                                 genres=["Horror"], poster_url="p"),
                ]

        watched1 = [_film("Seen A", genres=("Horror",))]
        watched2 = [_film("Seen B", genres=("Horror",))]
        # One thin watchlist film each → pool below n, discover widens it.
        bridge = asyncio.run(
            _blend_bridge_films(
                watched1, watched2,
                [_film("Only WL", genres=("Horror",))], [],
                enricher=_FakeEnricher(), n=5,
            )
        )
        by_title = {f.title: f for f in bridge}
        self.assertIn("The Prophecy", by_title)
        self.assertEqual(by_title["The Prophecy"].slug, "the-prophecy")
        self.assertTrue(all(f.slug for f in bridge))


if __name__ == "__main__":
    unittest.main()
