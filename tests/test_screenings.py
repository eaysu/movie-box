import asyncio
import unittest
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from app.screenings import (
    LOCAL_TZ,
    build_digest,
    ingest_release_layer,
    normalize_title,
    resolve_screening_title,
    week_start,
)


class TitleNormalisationTests(unittest.TestCase):
    def test_turkish_dotted_and_dotless_i_compare_equal(self):
        # str.lower() maps I→i, which would make "KIŞ" and "Kış" differ.
        self.assertEqual(normalize_title("KIŞ UYKUSU"), normalize_title("Kış Uykusu"))
        self.assertEqual(normalize_title("İKLİMLER"), normalize_title("İklimler"))

    def test_trailing_year_and_punctuation_are_stripped(self):
        self.assertEqual(
            normalize_title("Sonbahar Sonatı (1978)"), normalize_title("Sonbahar Sonatı")
        )
        self.assertEqual(normalize_title("Wall·E"), normalize_title("Wall E"))

    def test_blank_titles_normalise_to_empty(self):
        self.assertEqual(normalize_title("  "), "")
        self.assertEqual(normalize_title(None), "")


class TitleResolutionTests(unittest.TestCase):
    def _catalog(self):
        return {
            normalize_title("Sonbahar Sonatı"): {
                "tmdb_id": 12345,
                "film_slug": "autumn-sonata",
                "poster_url": "https://example.com/p.jpg",
                "release_year": 1978,
            },
        }

    def test_catalog_hit_costs_no_tmdb_call(self):
        calls = []

        class _Enricher:
            async def search_movie_candidates(self, *args, **kwargs):
                calls.append(args)
                return []

        result = asyncio.run(resolve_screening_title(
            "SONBAHAR SONATI", 1978, catalog=self._catalog(), enricher=_Enricher()
        ))

        self.assertEqual(result["match_status"], "matched")
        self.assertEqual(result["tmdb_id"], 12345)
        self.assertEqual(calls, [])

    def test_turkish_distribution_title_resolves_through_search(self):
        class _Enricher:
            def __init__(self):
                self.languages = []

            async def search_movie_candidates(self, title, *, year=None, language="tr-TR"):
                self.languages.append(language)
                return [{
                    "tmdb_id": 999,
                    "title": "Yaban Çilekleri",
                    "original_title": "Smultronstället",
                    "year": 1957,
                    "poster_url": "https://example.com/w.jpg",
                }]

        enricher = _Enricher()
        result = asyncio.run(resolve_screening_title(
            "Yaban Çilekleri", 1957, catalog={}, enricher=enricher
        ))

        self.assertEqual(result["match_status"], "matched")
        self.assertEqual(result["tmdb_id"], 999)
        self.assertEqual(enricher.languages[0], "tr-TR")

    def test_two_equally_named_films_stay_ambiguous(self):
        class _Enricher:
            async def search_movie_candidates(self, title, *, year=None, language="tr-TR"):
                return [
                    {"tmdb_id": 1, "title": "Kız Kardeşler", "original_title": "", "year": 1998},
                    {"tmdb_id": 2, "title": "Kız Kardeşler", "original_title": "", "year": 2019},
                ]

        result = asyncio.run(resolve_screening_title(
            "Kız Kardeşler", None, catalog={}, enricher=_Enricher()
        ))

        self.assertEqual(result["match_status"], "ambiguous")

    def test_unknown_title_without_tmdb_is_unresolved_not_guessed(self):
        result = asyncio.run(resolve_screening_title(
            "Bilinmeyen Film", None, catalog={}, enricher=None
        ))

        self.assertEqual(result["match_status"], "unresolved")
        self.assertIsNone(result.get("tmdb_id"))


class DigestTests(unittest.TestCase):
    def _screenings(self):
        return [
            {"title_raw": "Stalker", "tmdb_id": 1, "film_slug": "stalker",
             "venue_name": "Türkiye vizyonu", "genres": [], "director": ""},
            {"title_raw": "Yaban Çilekleri", "tmdb_id": 2, "film_slug": "wild-strawberries",
             "venue_name": "Kadıköy Sineması", "starts_at": "2026-09-05T21:30:00+03:00",
             "genres": [], "director": ""},
            {"title_raw": "Yeni Vizyon", "tmdb_id": 3, "film_slug": "yeni-vizyon",
             "venue_name": "Türkiye vizyonu", "genres": ["Drama"], "director": ""},
        ]

    def test_sections_are_ordered_and_labelled_by_actionability(self):
        watched = [{
            "tmdb_id": 2, "film_slug": "wild-strawberries", "title": "Yaban Çilekleri",
            "user_rating": 4.5, "rating_observed": True, "first_seen_at": "2021-04-02T10:00:00Z",
        }]

        digest = build_digest(
            self._screenings(), watched, ["stalker"], {"top_genres": ["Drama"]},
        )

        keys = [section["key"] for section in digest["sections"]]
        self.assertEqual(keys, ["watchlist", "back", "taste"])
        self.assertEqual(digest["sections"][0]["films"][0]["title"], "Stalker")
        self.assertIn("2021", digest["sections"][1]["films"][0]["note"])
        self.assertEqual(digest["total"], 3)

    def test_low_rated_rewatches_are_not_advertised_as_back_on_screen(self):
        watched = [{
            "tmdb_id": 2, "film_slug": "wild-strawberries", "title": "Yaban Çilekleri",
            "user_rating": 2.0, "rating_observed": True, "first_seen_at": "2021-04-02T10:00:00Z",
        }]

        digest = build_digest(self._screenings(), watched, [], {})

        self.assertNotIn("back", [section["key"] for section in digest["sections"]])

    def test_empty_sections_collapse_instead_of_rendering_placeholders(self):
        digest = build_digest(self._screenings(), [], [], {})

        for section in digest["sections"]:
            self.assertTrue(section["films"])

    def test_watched_films_never_appear_as_new_releases(self):
        watched = [{
            "tmdb_id": 3, "film_slug": "yeni-vizyon", "title": "Yeni Vizyon",
            "user_rating": None, "rating_observed": False, "first_seen_at": "2026-01-01T00:00:00Z",
        }]

        digest = build_digest(self._screenings(), watched, [], {"top_genres": ["Drama"]})
        titles = [film["title"] for section in digest["sections"] for film in section["films"]]

        self.assertNotIn("Yeni Vizyon", titles)


class ReleaseIngestTests(unittest.TestCase):
    class _Service:
        def __init__(self, claimed=True):
            self.claimed = claimed
            self.rows = None
            self.failures = []

        def claim_venue_ingest(self, slug, token, lease, min_age):
            return self.claimed

        def upsert_screenings(self, slug, rows, run_id):
            self.rows = rows
            return len(rows)

        def record_venue_failure(self, slug, error):
            self.failures.append(error)

    class _Enricher:
        def __init__(self, films=None, error=None):
            self.films = films or []
            self.error = error

        async def fetch_now_playing(self, region="TR"):
            if self.error:
                raise self.error
            return self.films

    def _settings(self):
        return SimpleNamespace(
            has_tmdb=True, bulletin_region="TR", bulletin_ingest_interval_hours=12
        )

    def test_release_rows_are_written_as_already_matched(self):
        service = self._Service()
        enricher = self._Enricher([
            {"tmdb_id": 7, "title": "Vizyon Filmi", "year": 2026, "poster_url": "https://x/p.jpg"},
        ])

        written = asyncio.run(ingest_release_layer(service, self._settings(), enricher=enricher))

        self.assertEqual(written, 1)
        self.assertEqual(service.rows[0]["match_status"], "matched")
        self.assertEqual(service.rows[0]["tmdb_id"], 7)

    def test_a_held_lease_skips_the_run(self):
        service = self._Service(claimed=False)
        enricher = self._Enricher([{"tmdb_id": 7, "title": "Vizyon", "year": 2026}])

        self.assertEqual(
            asyncio.run(ingest_release_layer(service, self._settings(), enricher=enricher)), 0
        )
        self.assertIsNone(service.rows)

    def test_a_tmdb_failure_is_recorded_and_never_raised(self):
        service = self._Service()
        enricher = self._Enricher(error=RuntimeError("tmdb down"))

        written = asyncio.run(ingest_release_layer(service, self._settings(), enricher=enricher))

        self.assertEqual(written, 0)
        self.assertIn("tmdb down", service.failures[0])


class WeekTests(unittest.TestCase):
    def test_week_starts_on_the_local_monday(self):
        friday = datetime(2026, 9, 4, 23, 30, tzinfo=LOCAL_TZ)
        self.assertEqual(week_start(friday).isoformat(), "2026-08-31")

    def test_late_sunday_utc_still_belongs_to_the_local_week(self):
        # 22:30 UTC Sunday is already Monday 01:30 in Istanbul.
        late = datetime(2026, 9, 6, 22, 30, tzinfo=timezone.utc)
        self.assertEqual(week_start(late).isoformat(), "2026-09-07")
        self.assertEqual(week_start(late - timedelta(hours=2)).isoformat(), "2026-08-31")


if __name__ == "__main__":
    unittest.main()
