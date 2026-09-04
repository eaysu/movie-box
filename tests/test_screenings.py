import asyncio
import unittest
from pathlib import Path
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from app.screenings import (
    LOCAL_TZ,
    parse_programme,
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
        # first_seen_at is when the sync first saw the film, not when it was
        # watched, so the note must not print it as a viewing year.
        note = digest["sections"][1]["films"][0]["note"]
        self.assertIn("4.5", note)
        self.assertNotIn("2021", note)
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

    def test_watchlist_matches_on_tmdb_id_when_the_slug_is_missing(self):
        """A screening resolved through TMDb has no Letterboxd slug, and every
        watchlist is keyed by slug — matching on either is what makes the
        section fire at all."""
        rows = [{"title_raw": "Stalker", "tmdb_id": 1, "film_slug": None,
                 "venue_name": "Atlas", "genres": [], "director": ""}]

        digest = build_digest(rows, [], [{"slug": "stalker", "tmdb_id": 1}], {})

        self.assertEqual(digest["sections"][0]["key"], "watchlist")

    def test_one_film_at_several_venues_is_one_card(self):
        rows = [
            {"title_raw": "Stalker", "tmdb_id": 1, "film_slug": "stalker",
             "venue_name": "Atlas", "genres": [], "director": ""},
            {"title_raw": "Stalker", "tmdb_id": 1, "film_slug": "stalker",
             "venue_name": "Kadıköy", "genres": [], "director": ""},
        ]

        digest = build_digest(rows, [], ["stalker"], {})
        films = digest["sections"][0]["films"]

        self.assertEqual(len(films), 1)
        self.assertEqual(films[0]["venue"], "Atlas · Kadıköy")

    def test_taste_notes_use_turkish_genre_names(self):
        rows = [{"title_raw": "Yeni Film", "tmdb_id": 9, "film_slug": "yeni-film",
                 "venue_name": "Vizyon", "genres": ["Adventure"], "director": ""}]

        digest = build_digest(rows, [], [], {"top_genres": ["Adventure"]})

        self.assertIn("Macera", digest["sections"][0]["films"][0]["note"])

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


class VenueParserTests(unittest.TestCase):
    """Pinned against trimmed copies of the real programme pages.

    When a venue redesigns, this is the test that fails first, and the fix is a
    `venues.config` change plus a refreshed fixture — not application code.
    """

    FIXTURES = Path(__file__).parent / "fixtures" / "venues"

    def _parse(self, fixture, config, base_url):
        html = (self.FIXTURES / fixture).read_text(encoding="utf-8")
        return parse_programme(html, config, base_url)

    def test_paribu_cineverse_reads_titles_from_the_data_attribute(self):
        rows = self._parse("paribu_cineverse.html", {
            "strategy": "attr",
            "item_selector": "div.movie-list-banner-item",
            "title_attr": "data-movie-title",
            "link_attr": "data-slug-url",
        }, "https://www.paribucineverse.com/vizyondakiler")

        self.assertTrue(rows)
        self.assertIn("Fall 2: Ölümcül Tırmanış", [row["title_raw"] for row in rows])
        self.assertTrue(rows[0]["url"].startswith("https://www.paribucineverse.com/"))

    def test_baska_sinema_reads_the_card_title_not_the_details_link(self):
        rows = self._parse("baska_sinema.html", {
            "strategy": "css",
            "item_selector": "div.movie_box",
            "title_selector": "h3.movie_title",
            "link_selector": "div.movie_cover a[href]",
        }, "https://www.baskasinema.com/filmler/")

        titles = [row["title_raw"] for row in rows]
        self.assertTrue(titles)
        self.assertNotIn("Detaylar", titles)
        self.assertTrue(all(row["url"].startswith("https://") for row in rows))

    def test_atlas_link_strategy_skips_call_to_action_anchors(self):
        rows = self._parse("atlas_1948.html", {
            "strategy": "link",
            "href_pattern": r"/film/[^/]+/?$",
            "skip_titles": ["BİLETİNİ AL", "Detaylar", "İncele", "Seanslar"],
        }, "https://www.atlas1948.com/")

        titles = [row["title_raw"] for row in rows]
        self.assertTrue(titles)
        for junk in ("BİLETİNİ AL", "Biletini Al"):
            self.assertNotIn(junk, titles)

    def test_kadikoy_listing_parses_and_non_film_events_stay_unresolved(self):
        rows = self._parse("kadikoy_sinemasi.html", {
            "strategy": "css",
            "item_selector": "div.yeniMekan__sayfalar__vizyondakiler li",
            "title_selector": "h3 a",
        }, "https://biletinial.com/tr-tr/mekan/kadikoy-sinemasi")

        self.assertTrue(rows)
        # The venue also lists stand-up nights; they simply never resolve to a
        # film, which is why the matcher refuses to guess.
        stand_up = next(
            (row for row in rows if "Gösteri" in row["title_raw"]), None
        )
        if stand_up:
            resolved = asyncio.run(resolve_screening_title(
                stand_up["title_raw"], None, catalog={}, enricher=None
            ))
            self.assertEqual(resolved["match_status"], "unresolved")

    def test_duplicate_titles_on_one_page_collapse(self):
        html = """<html><body>
          <div class="movie-list-banner-item" data-movie-title="Aynı Film" data-slug-url="/a"></div>
          <div class="movie-list-banner-item" data-movie-title="AYNI FİLM" data-slug-url="/b"></div>
        </body></html>"""
        rows = parse_programme(html, {
            "strategy": "attr",
            "item_selector": "div.movie-list-banner-item",
            "title_attr": "data-movie-title",
            "link_attr": "data-slug-url",
        }, "https://example.com/")

        self.assertEqual(len(rows), 1)


class VenueConfigTests(unittest.TestCase):
    def test_every_seeded_venue_records_its_robots_check(self):
        schema = (Path(__file__).parents[1] / "supabase" / "schema.sql").read_text()
        seed = schema.split("INSERT INTO public.venues (slug, name, city, kind, source_url, config)", 1)[1]
        seed = seed.split("ON CONFLICT", 1)[0]

        for slug in ("paribu-cineverse", "baska-sinema", "atlas-1948", "kadikoy-sinemasi"):
            self.assertIn(slug, seed)
        # A venue may only be enabled after someone checked its terms.
        self.assertEqual(seed.count('"robots"'), 4)
        self.assertEqual(seed.count('"checked"'), 4)


class VenueResilienceTests(unittest.TestCase):
    class _Service:
        def __init__(self, venues):
            self.venues = venues
            self.written = {}
            self.failures = {}

        def list_active_venues(self, kind=None):
            return self.venues

        def claim_venue_ingest(self, slug, token, lease, min_age):
            return True

        def upsert_screenings(self, slug, rows, run_id):
            self.written[slug] = rows
            return len(rows)

        def record_venue_failure(self, slug, error):
            self.failures[slug] = error

    def test_one_broken_venue_does_not_stop_the_others(self):
        from app import screenings as module

        service = self._Service([
            {"slug": "release", "kind": "release"},
            {"slug": "broken", "kind": "repertory", "source_url": "https://broken.example"},
            {"slug": "healthy", "kind": "repertory", "source_url": "https://healthy.example"},
        ])

        async def fetch(venue):
            if venue["slug"] == "broken":
                raise RuntimeError("site down")
            return [{"title_raw": "Stalker", "url": "https://healthy.example/stalker"}]

        original = module._fetch_and_parse
        module._fetch_and_parse = fetch
        try:
            written = asyncio.run(module.ingest_venues(service, enricher=None))
        finally:
            module._fetch_and_parse = original

        self.assertEqual(written, 1)
        self.assertIn("healthy", service.written)
        self.assertIn("site down", service.failures["broken"])
        # The release layer has its own ingest and is skipped here.
        self.assertNotIn("release", service.written)


class DigestCacheTests(unittest.TestCase):
    """An empty week must not be frozen for seven days.

    The first version cached whatever it computed, so a card built while the
    programme was still being ingested pinned "nothing found" until Monday.
    """

    def test_empty_digest_is_not_persisted(self):
        main = (Path(__file__).parents[1] / "app" / "main.py").read_text()
        bulletin = main.split('@app.get("/api/bulletin")', 1)[1].split("@app.get", 1)[0]

        self.assertIn('if digest.get("total"):', bulletin)
        save_at = bulletin.index("save_bulletin_digest")
        guard_at = bulletin.index('if digest.get("total"):')
        self.assertLess(guard_at, save_at)

    def test_a_new_programme_invalidates_the_weeks_cards(self):
        main = (Path(__file__).parents[1] / "app" / "main.py").read_text()
        auth = (Path(__file__).parents[1] / "app" / "auth.py").read_text()

        self.assertIn("clear_bulletin_digests", main)
        self.assertIn("def clear_bulletin_digests", auth)
