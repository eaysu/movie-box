from pathlib import Path

from scripts.admin_users import _normalise, _short_date


ROOT = Path(__file__).resolve().parents[1]


def test_admin_username_normalisation_and_date_formatting():
    assert _normalise("  @EnesAysu ") == "enesaysu"
    assert _short_date("2026-09-02T10:20:30+00:00") == "2026-09-02 10:20"
    assert _short_date(None) == "-"


def test_activity_schema_is_service_role_only_and_has_report_function():
    schema = (ROOT / "supabase" / "schema.sql").read_text()
    assert "CREATE TABLE IF NOT EXISTS public.user_activity_events" in schema
    assert "CREATE OR REPLACE FUNCTION public.admin_user_activity_report" in schema
    assert "REVOKE ALL ON TABLE public.user_activity_events FROM anon, authenticated" in schema
    assert "GRANT EXECUTE ON FUNCTION public.admin_user_activity_report(BOOLEAN)" in schema


def test_report_tracks_recommendation_and_sync_lifecycle_events():
    schema = (ROOT / "supabase" / "schema.sql").read_text()
    main = (ROOT / "app" / "main.py").read_text()
    sync = (ROOT / "app" / "profile_sync.py").read_text()
    assert "recommendation_successes" in schema
    assert "recommendation_completed" in main
    assert "profile_sync_completed" in sync
    assert "random_completed" in main
    from app.auth import AuthService

    assert hasattr(AuthService, "record_activity_event")
