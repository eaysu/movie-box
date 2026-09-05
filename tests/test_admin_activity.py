from pathlib import Path
from types import SimpleNamespace

from scripts.admin_users import (
    _normalise,
    _print_table,
    _short_date,
    _sort_by_activity,
)


ROOT = Path(__file__).resolve().parents[1]


def test_admin_username_normalisation_and_date_formatting():
    assert _normalise("  @EnesAysu ") == "enesaysu"
    # Supabase stores UTC; the report prints Türkiye time (UTC+3).
    assert _short_date("2026-09-02T10:20:30+00:00") == "2026-09-02 13:20"
    assert _short_date("2026-09-02T22:30:00+00:00") == "2026-09-03 01:30"
    assert _short_date(None) == "-"


def test_activity_schema_is_service_role_only_and_has_report_function():
    schema = (ROOT / "supabase" / "schema.sql").read_text()
    assert "CREATE TABLE IF NOT EXISTS public.user_activity_events" in schema
    assert "CREATE OR REPLACE FUNCTION public.admin_user_activity_report" in schema
    assert "REVOKE ALL ON TABLE public.user_activity_events FROM anon, authenticated" in schema
    assert "GRANT EXECUTE ON FUNCTION public.admin_user_activity_report(BOOLEAN)" in schema


def test_report_exposes_letter_volume_and_visibility_without_content():
    schema = (ROOT / "supabase" / "schema.sql").read_text()
    for column in (
        "letters_sent BIGINT",
        "letters_received BIGINT",
        "letters_unread BIGINT",
        "last_letter_at TIMESTAMPTZ",
        "discoverable BOOLEAN",
        "letter_receiving_enabled BOOLEAN",
    ):
        assert column in schema
    body = schema.split("CREATE OR REPLACE FUNCTION public.admin_user_activity_report", 1)[1]
    report = body.split("\n$$;", 1)[0]
    # Volume only: the report must never select an encrypted envelope field.
    # ("iv" is checked as a column reference; it is a substring of other words.)
    for secret in ("ciphertext", "salt", "public_key", ".iv", " iv,"):
        assert secret not in report


def test_table_numbers_rows_and_renders_letter_and_visibility_columns(capsys):
    rows = [
        {
            "username": "enesaysu",
            "account_status": "active",
            "discoverable": True,
            "letter_receiving_enabled": True,
            "letters_sent": 2,
            "letters_received": 1,
            "letters_unread": 1,
            "last_letter_at": "2026-09-03T10:20:30+00:00",
        },
        {
            "username": "ikinci",
            "account_status": "active",
            "discoverable": False,
            "letter_receiving_enabled": False,
            "letters_sent": 0,
            "letters_received": 0,
            "letters_unread": 0,
            "last_letter_at": None,
        },
    ]
    _print_table(rows)
    output = capsys.readouterr().out
    lines = output.splitlines()
    assert lines[0].startswith("#")
    assert lines[2].split()[0] == "1"
    assert lines[3].split()[0] == "2"
    assert "online" in output and "offline" in output
    assert "2/1/1" in output
    assert "1 kullanıcı toplam 2 mektup yolladı" in output


def test_rows_are_ordered_by_most_recent_activity():
    rows = [
        {"username": "dormant", "created_at": "2026-08-01T09:00:00+00:00",
         "last_activity_at": "2026-08-02T09:00:00+00:00"},
        {"username": "active", "created_at": "2026-06-01T09:00:00+00:00",
         "last_activity_at": "2026-09-04T08:00:00+00:00"},
        # No event yet: falls back to its sync time, so a fresh registration
        # does not sink below a long-dormant account.
        {"username": "fresh", "created_at": "2026-09-03T12:00:00+00:00",
         "profile_synced_at": "2026-09-03T12:30:00+00:00"},
        {"username": "never", "created_at": "2026-05-01T09:00:00+00:00"},
    ]
    assert [row["username"] for row in _sort_by_activity(rows)] == [
        "active",
        "fresh",
        "dormant",
        "never",
    ]


def test_schema_orders_report_by_activity():
    schema = (ROOT / "supabase" / "schema.sql").read_text()
    body = schema.split("CREATE OR REPLACE FUNCTION public.admin_user_activity_report", 1)[1]
    report = body.split("\n$$;", 1)[0]
    assert "ORDER BY COALESCE(events.last_activity_at" in report


def test_table_degrades_when_report_function_is_outdated(capsys):
    _print_table([{"username": "enesaysu", "account_status": "active"}])
    output = capsys.readouterr().out
    assert "güncel supabase/schema.sql" in output
    assert "toplam" not in output.split("Mektup ve görünürlük")[1]


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


def test_letter_sender_repair_only_touches_active_closed_senders():
    """Only accounts stuck in the one-way state are repaired.

    A member who never sent a letter has not opted into the feature, and a
    disabled account must not be reactivated by a maintenance script.
    """
    from scripts.fix_letter_senders import find_affected

    class _Table:
        def __init__(self, client, name):
            self.client, self.name = client, name

        def select(self, *_args):
            return self

        def in_(self, _column, values):
            self.values = values
            return self

        def execute(self):
            if self.name == "cinephile_letters":
                return SimpleNamespace(data=[
                    {"sender_user_id": 1}, {"sender_user_id": 1}, {"sender_user_id": 2},
                    {"sender_user_id": 3},
                ])
            return SimpleNamespace(data=[
                {"id": 1, "username": "closed_sender", "account_status": "active",
                 "letter_receiving_enabled": False},
                {"id": 2, "username": "open_sender", "account_status": "active",
                 "letter_receiving_enabled": True},
                {"id": 3, "username": "disabled_sender", "account_status": "disabled",
                 "letter_receiving_enabled": False},
            ])

    class _Client:
        def table(self, name):
            return _Table(self, name)

    affected = find_affected(_Client())

    self_usernames = [row["username"] for row in affected]
    assert self_usernames == ["closed_sender"]
    assert affected[0]["sent"] == 2
