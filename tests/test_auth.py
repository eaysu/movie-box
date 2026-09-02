import asyncio
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient
from starlette.requests import Request

from app import main
from app.auth import Account, AuthService, AuthSession, TransientStorageError, validate_password
from app.scraper import AccessBlockedError


def _settings(**overrides):
    values = {
        "has_auth": True,
        "has_supabase": True,
        "supabase_url": "https://project.supabase.co",
        "supabase_key": "service-key",
        "supabase_anon_key": "anon-key",
        "auth_identity_secret": "test-identity-secret",
        "auth_cookie_secure": True,
        "auth_session_max_age": 604800,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def _account(username="film_fan"):
    return Account(
        id=7,
        auth_user_id="00000000-0000-0000-0000-000000000007",
        username=username,
        display_name="Film Fan",
    )


def test_password_confirmation_and_policy():
    assert validate_password("long-enough-password", "long-enough-password")
    with pytest.raises(ValueError, match="en az 10"):
        validate_password("short")
    with pytest.raises(ValueError, match="eşleşmiyor"):
        validate_password("long-enough-password", "different-password")


def test_synthetic_identity_is_stable_and_does_not_expose_username():
    service = AuthService(_settings(), client_factory=lambda *_args: None)
    first = service.identity_email("film_fan")
    assert first == service.identity_email("film_fan")
    assert first != service.identity_email("other_user")
    assert "film_fan" not in first
    assert first.endswith("@users.movieboxd.invalid")


def test_service_role_client_reuses_connection_pool_but_auth_client_does_not():
    created = []

    def factory(_url, key):
        client = SimpleNamespace(key=key, number=len(created) + 1)
        created.append(client)
        return client

    service = AuthService(_settings(), client_factory=factory)
    assert service._service_client() is service._service_client()
    assert len(created) == 1
    assert service._auth_client() is not service._auth_client()
    assert len(created) == 3


def test_short_account_cache_avoids_repeat_validation_and_can_be_invalidated():
    token = "unique-account-cache-token"
    account = _account("cached_fan")
    calls = []
    fake_service = SimpleNamespace(
        current_account=lambda value: calls.append(value) or account
    )

    def request_for(value):
        return Request({
            "type": "http",
            "method": "GET",
            "path": "/api/auth/me",
            "headers": [(b"cookie", f"mb_access={value}".encode())],
        })

    main._invalidate_account_cache(token)
    with patch("app.main._auth_service", return_value=fake_service):
        assert asyncio.run(main._require_account(request_for(token))) == account
        assert asyncio.run(main._require_account(request_for(token))) == account
        assert calls == [token]
        assert token not in repr(main._account_cache)

        main._invalidate_account_cache(token)
        assert asyncio.run(main._require_account(request_for(token))) == account
        assert calls == [token, token]
    main._invalidate_account_cache(token)


def test_full_history_sync_schema_is_service_role_only():
    schema = (Path(__file__).parents[1] / "supabase" / "schema.sql").read_text()
    assert "CREATE TABLE IF NOT EXISTS public.user_watched_films (" in schema
    assert "CREATE TABLE IF NOT EXISTS public.profile_sync_jobs (" in schema
    assert "CREATE OR REPLACE FUNCTION public.upsert_watched_films(" in schema
    # New tables lock out browser roles like every other user table.
    for line in (
        "ALTER TABLE public.user_watched_films ENABLE ROW LEVEL SECURITY;",
        "ALTER TABLE public.profile_sync_jobs ENABLE ROW LEVEL SECURITY;",
        "REVOKE ALL ON TABLE public.user_watched_films FROM anon, authenticated;",
        "REVOKE ALL ON TABLE public.profile_sync_jobs FROM anon, authenticated;",
        "GRANT ALL ON TABLE public.user_watched_films TO service_role;",
        "GRANT ALL ON TABLE public.profile_sync_jobs TO service_role;",
        "REVOKE ALL ON FUNCTION public.upsert_watched_films(BIGINT, JSONB)",
        "GRANT EXECUTE ON FUNCTION public.upsert_watched_films(BIGINT, JSONB)",
        "CREATE TABLE IF NOT EXISTS public.film_posters (",
        "CREATE OR REPLACE FUNCTION public.upsert_film_posters(",
        "ALTER TABLE public.film_posters ENABLE ROW LEVEL SECURITY;",
        "REVOKE ALL ON TABLE public.film_posters FROM anon, authenticated;",
        "GRANT ALL ON TABLE public.film_posters TO service_role;",
        "GRANT EXECUTE ON FUNCTION public.upsert_film_posters(JSONB) TO service_role;",
        "CREATE TABLE IF NOT EXISTS public.director_images (",
        "CREATE OR REPLACE FUNCTION public.upsert_director_images(",
        "ALTER TABLE public.director_images ENABLE ROW LEVEL SECURITY;",
        "CREATE OR REPLACE FUNCTION public.claim_profile_sync_job(",
        "CREATE OR REPLACE FUNCTION public.finalize_profile_sync_run(",
        "COALESCE(last_seen_run_id = p_sync_run_id, FALSE)",
        "CREATE INDEX IF NOT EXISTS idx_film_posters_tmdb_id",
        "ALTER TABLE public.film_posters ALTER COLUMN poster_url DROP NOT NULL;",
        "ADD COLUMN IF NOT EXISTS overview TEXT NOT NULL DEFAULT '';",
        "details_loaded = public.film_posters.details_loaded OR EXCLUDED.details_loaded",
    ):
        assert line in schema


class _RecordingTable:
    def __init__(self, name, log):
        self.name = name
        self._log = log

    def select(self, columns):
        self._log.append((self.name, columns))
        return self

    def limit(self, _n):
        return self

    def execute(self):
        return SimpleNamespace(data=[], count=0)


class _RecordingClient:
    def __init__(self):
        self.calls = []

    def table(self, name):
        return _RecordingTable(name, self.calls)


def test_check_sync_schema_probes_only_the_new_tables_with_zero_rows():
    client = _RecordingClient()
    service = AuthService(_settings(), client_factory=lambda *_args: client)
    assert service.check_sync_schema() is True
    probed = {name for name, _cols in client.calls}
    assert probed == {
        "user_watched_films", "profile_sync_jobs", "director_images", "film_posters"
    }


def test_readiness_requires_discovery_visibility_column():
    client = _RecordingClient()
    service = AuthService(_settings(), client_factory=lambda *_args: client)

    assert service.check_schema() is True
    users_query = next(columns for name, columns in client.calls if name == "users")
    assert "discoverable" in users_query


def test_transient_cloudflare_storage_read_retries_then_returns_clear_error():
    service = AuthService(_settings(), client_factory=lambda *_args: None)
    attempts = []

    def unavailable():
        attempts.append(True)
        raise RuntimeError("Cloudflare 400 Bad Request: JSON could not be generated")

    with patch("app.auth.time.sleep") as sleep:
        with pytest.raises(TransientStorageError, match="Veri bağlantısı"):
            service._retry_storage_read(unavailable)

    assert len(attempts) == 3
    assert sleep.call_count == 2


@pytest.mark.parametrize(
    "message",
    [
        "httpx.RemoteProtocolError: Server disconnected",
        "httpx.RemoteProtocolError: <ConnectionTerminated error_code:1>",
        "httpx.WriteError: EOF occurred in violation of protocol (_ssl.c:2417)",
    ],
)
def test_transient_storage_read_retries_transport_disconnects(message):
    service = AuthService(_settings(), client_factory=lambda *_args: None)
    attempts = []

    def unavailable():
        attempts.append(True)
        raise RuntimeError(message)

    with patch("app.auth.time.sleep"):
        with pytest.raises(TransientStorageError, match="Veri bağlantısı"):
            service._retry_storage_read(unavailable)

    assert len(attempts) == 3


def test_login_sets_http_only_session_and_readable_csrf_cookies():
    session = AuthSession(
        account=_account(),
        access_token="access-token",
        refresh_token="refresh-token",
        expires_in=3600,
    )
    fake_service = SimpleNamespace(login=lambda *_args, **_kwargs: session)
    with (
        patch("app.main.get_settings", return_value=_settings()),
        patch("app.main._auth_service", return_value=fake_service),
        patch("app.main._enforce_auth_rate_limit", new=AsyncMock()),
        TestClient(main.app, base_url="https://testserver") as client,
    ):
        response = client.post(
            "/api/auth/login",
            json={"username": "film_fan", "password": "long-enough-password"},
        )

    assert response.status_code == 200
    cookies = response.headers.get_list("set-cookie")
    access = next(item for item in cookies if item.startswith("mb_access="))
    refresh = next(item for item in cookies if item.startswith("mb_refresh="))
    csrf = next(item for item in cookies if item.startswith("mb_csrf="))
    assert "HttpOnly" in access and "Secure" in access and "SameSite=lax" in access
    assert "HttpOnly" in refresh
    assert "HttpOnly" not in csrf and "Secure" in csrf


def test_account_mode_rejects_state_change_without_csrf_before_work_starts():
    with (
        patch("app.main.get_settings", return_value=_settings()),
        patch("app.main._enforce_heavy_rate_limit", new=AsyncMock()),
        TestClient(main.app, base_url="https://testserver") as client,
    ):
        response = client.post("/api/random", json={"username": "film_fan"})

    assert response.status_code == 403
    assert response.json()["detail"] == "Güvenlik doğrulaması başarısız."


def test_register_password_mismatch_stops_before_scraping():
    scrape = AsyncMock()
    with (
        patch("app.main.get_settings", return_value=_settings()),
        patch("app.main._enforce_auth_rate_limit", new=AsyncMock()),
        patch("app.main.scrape_profile", new=scrape),
        TestClient(main.app, base_url="https://testserver") as client,
    ):
        response = client.post(
            "/api/auth/register/start",
            json={
                "username": "film_fan",
                "password": "long-enough-password",
                "password_confirm": "different-password",
            },
        )

    assert response.status_code == 422
    scrape.assert_not_awaited()


def test_registration_maps_letterboxd_block_to_retryable_service_error():
    scrape = AsyncMock(
        side_effect=AccessBlockedError("Letterboxd HTTP 403", status=403)
    )
    with (
        patch("app.main.get_settings", return_value=_settings(scrape_max_retries=3)),
        patch("app.main._enforce_auth_rate_limit", new=AsyncMock()),
        patch("app.main.scrape_profile", new=scrape),
        TestClient(main.app, base_url="https://testserver") as client,
    ):
        response = client.post(
            "/api/auth/register/start",
            json={
                "username": "film_fan",
                "password": "long-enough-password",
                "password_confirm": "long-enough-password",
            },
        )

    assert response.status_code == 503
    assert response.headers["retry-after"] == "60"
    assert "geçici olarak sınırladı" in response.json()["detail"]


def test_authenticated_user_can_create_consent_based_blend_request():
    account = _account()
    fake_service = SimpleNamespace(
        current_account=lambda _token: account,
        find_blend_relation=lambda *_args: None,
        create_blend_request=lambda *_args, **_kwargs: "request-123",
    )
    with (
        patch("app.main.get_settings", return_value=_settings()),
        patch("app.main._auth_service", return_value=fake_service),
        patch("app.main._enforce_auth_rate_limit", new=AsyncMock()),
        TestClient(main.app, base_url="https://testserver") as client,
    ):
        response = client.post(
            "/api/blends/requests",
            json={"recipient_username": "other_user"},
            headers={
                "Cookie": "mb_access=access-token; mb_csrf=csrf-token",
                "X-CSRF-Token": "csrf-token",
            },
        )

    assert response.status_code == 200
    assert response.json() == {
        "ok": True,
        "request_id": "request-123",
        "recipient_username": "other_user",
        "status": "pending",
        "existing": False,
    }


@pytest.mark.parametrize(
    ("relation", "expected_status", "expected_direction"),
    [
        (
            {"request_id": "accepted-1", "status": "accepted", "direction": "outgoing"},
            "accepted",
            "outgoing",
        ),
        (
            {"request_id": "pending-1", "status": "pending", "direction": "incoming"},
            "pending",
            "incoming",
        ),
    ],
)
def test_existing_blend_relation_is_returned_instead_of_creating_a_duplicate(
    relation, expected_status, expected_direction
):
    account = _account()
    created = []
    fake_service = SimpleNamespace(
        current_account=lambda _token: account,
        find_blend_relation=lambda *_args: relation,
        create_blend_request=lambda *_args, **_kwargs: created.append(True),
    )
    with (
        patch("app.main.get_settings", return_value=_settings()),
        patch("app.main._auth_service", return_value=fake_service),
        patch("app.main._enforce_auth_rate_limit", new=AsyncMock()),
        TestClient(main.app, base_url="https://testserver") as client,
    ):
        response = client.post(
            "/api/blends/requests",
            json={"recipient_username": "other_user"},
            headers={
                "Cookie": "mb_access=access-token; mb_csrf=csrf-token",
                "X-CSRF-Token": "csrf-token",
            },
        )

    assert response.status_code == 200
    assert response.json()["existing"] is True
    assert response.json()["status"] == expected_status
    assert response.json()["direction"] == expected_direction
    assert created == []


def test_pending_blend_count_returns_numbered_inbox_badge_value():
    account = _account()
    fake_service = SimpleNamespace(
        current_account=lambda _token: account,
        count_pending_blend_requests=lambda _account: 12,
    )
    with (
        patch("app.main.get_settings", return_value=_settings()),
        patch("app.main._auth_service", return_value=fake_service),
        TestClient(main.app, base_url="https://testserver") as client,
    ):
        response = client.get(
            "/api/blends/pending-count",
            headers={"Cookie": "mb_access=access-token"},
        )

    assert response.status_code == 200
    assert response.json() == {"count": 12}


def test_rejecting_blend_does_not_run_comparison_engine():
    account = _account()
    fake_service = SimpleNamespace(
        current_account=lambda _token: account,
        decide_blend_request=lambda *_args, **_kwargs: {
            "id": "request-123",
            "status": "rejected",
        },
    )
    compute = AsyncMock()
    with (
        patch("app.main.get_settings", return_value=_settings()),
        patch("app.main._auth_service", return_value=fake_service),
        patch("app.main._accepted_blend_single_flight", new=compute),
        TestClient(main.app, base_url="https://testserver") as client,
    ):
        response = client.post(
            "/api/blends/requests/request-123/decision",
            json={"decision": "rejected"},
            headers={
                "Cookie": "mb_access=access-token; mb_csrf=csrf-token",
                "X-CSRF-Token": "csrf-token",
            },
        )

    assert response.status_code == 200
    assert response.json()["status"] == "rejected"
    compute.assert_not_awaited()


def test_accepting_blend_returns_persisted_comparison_result():
    account = _account()
    fake_service = SimpleNamespace(
        current_account=lambda _token: account,
        decide_blend_request=lambda *_args, **_kwargs: {
            "id": "request-123",
            "status": "accepted",
        },
    )
    computed = {"request_id": "request-123", "score": 82, "cached": False}
    with (
        patch("app.main.get_settings", return_value=_settings()),
        patch("app.main._auth_service", return_value=fake_service),
        patch("app.main._enforce_heavy_rate_limit", new=AsyncMock()),
        patch(
            "app.main._accepted_blend_single_flight",
            new=AsyncMock(return_value=computed),
        ),
        TestClient(main.app, base_url="https://testserver") as client,
    ):
        response = client.post(
            "/api/blends/requests/request-123/decision",
            json={"decision": "accepted"},
            headers={
                "Cookie": "mb_access=access-token; mb_csrf=csrf-token",
                "X-CSRF-Token": "csrf-token",
            },
        )

    assert response.status_code == 200
    assert response.json() == {"status": "accepted", "result": computed}


def test_block_endpoint_is_authenticated_and_csrf_protected():
    account = _account()
    blocked = []
    fake_service = SimpleNamespace(
        current_account=lambda _token: account,
        block_user=lambda _account, username: blocked.append(username),
    )
    with (
        patch("app.main.get_settings", return_value=_settings()),
        patch("app.main._auth_service", return_value=fake_service),
        patch("app.main._enforce_auth_rate_limit", new=AsyncMock()),
        TestClient(main.app, base_url="https://testserver") as client,
    ):
        missing_csrf = client.post("/api/users/other_user/block")
        response = client.post(
            "/api/users/other_user/block",
            headers={
                "Cookie": "mb_access=access-token; mb_csrf=csrf-token",
                "X-CSRF-Token": "csrf-token",
            },
        )

    assert missing_csrf.status_code == 403
    assert response.status_code == 200
    assert blocked == ["other_user"]


def test_report_rejects_unknown_category_before_service_call():
    account = _account()
    fake_service = SimpleNamespace(current_account=lambda _token: account)
    with (
        patch("app.main.get_settings", return_value=_settings()),
        patch("app.main._auth_service", return_value=fake_service),
        TestClient(main.app, base_url="https://testserver") as client,
    ):
        response = client.post(
            "/api/users/other_user/report",
            json={"category": "not-valid", "detail": "test"},
            headers={
                "Cookie": "mb_access=access-token; mb_csrf=csrf-token",
                "X-CSRF-Token": "csrf-token",
            },
        )

    assert response.status_code == 422


def test_password_reset_mismatch_stops_before_profile_scrape():
    scrape = AsyncMock()
    with (
        patch("app.main.get_settings", return_value=_settings()),
        patch("app.main._enforce_auth_rate_limit", new=AsyncMock()),
        patch("app.main.scrape_profile", new=scrape),
        TestClient(main.app, base_url="https://testserver") as client,
    ):
        response = client.post(
            "/api/auth/password-reset/finish",
            json={
                "username": "film_fan",
                "code": "MOVIEBOXD-ABC123",
                "new_password": "long-enough-password",
                "new_password_confirm": "different-password",
            },
        )

    assert response.status_code == 422
    scrape.assert_not_awaited()


def test_onboarding_completion_requires_full_crawl_milestone():
    account = _account()
    completed = []
    fake_service = SimpleNamespace(
        current_account=lambda _token: account,
        get_sync_job=lambda _uid: {
            "state": "running", "phase": "enrich", "scope": "full",
            "films_processed": 250, "films_total": 250,
        },
        complete_onboarding=lambda value: completed.append(value.id),
    )
    with (
        patch("app.main.get_settings", return_value=_settings()),
        patch("app.main._auth_service", return_value=fake_service),
        TestClient(main.app, base_url="https://testserver") as client,
    ):
        response = client.post(
            "/api/profile/onboarding-complete",
            headers={
                "Cookie": "mb_access=access-token; mb_csrf=csrf-token",
                "X-CSRF-Token": "csrf-token",
            },
        )

    assert response.status_code == 409
    assert completed == []


def test_sync_status_returns_progress_without_loading_profile_snapshot():
    account = _account()
    loaded_profiles = []
    fake_service = SimpleNamespace(
        current_account=lambda _token: account,
        get_sync_job=lambda _uid: {
            "state": "running",
            "phase": "enrich",
            "scope": "full",
            "films_processed": 125,
            "films_total": 250,
        },
        get_profile=lambda _account: loaded_profiles.append(True),
    )
    with (
        patch("app.main.get_settings", return_value=_settings()),
        patch("app.main._auth_service", return_value=fake_service),
        patch("app.main.profile_sync.is_running", return_value=True),
        TestClient(main.app, base_url="https://testserver") as client,
    ):
        response = client.get(
            "/api/profile/sync-status",
            headers={"Cookie": "mb_access=sync-status-token"},
        )

    assert response.status_code == 200
    assert response.json()["sync_job"] == {
        "state": "running",
        "phase": "enrich",
        "scope": "full",
        "processed": 125,
        "total": 250,
        "percent": 50,
        "onboarding_ready": False,
        "error": "",
    }
    assert loaded_profiles == []


def test_onboarding_completion_is_persisted_after_reveal_is_ready():
    account = _account()
    fake_service = SimpleNamespace(
        current_account=lambda _token: account,
        get_sync_job=lambda _uid: {
            "state": "done", "phase": "done", "scope": "full",
            "films_processed": 250, "films_total": 250,
        },
        complete_onboarding=lambda _account: "2026-08-31T12:00:00+00:00",
    )
    with (
        patch("app.main.get_settings", return_value=_settings()),
        patch("app.main._auth_service", return_value=fake_service),
        TestClient(main.app, base_url="https://testserver") as client,
    ):
        response = client.post(
            "/api/profile/onboarding-complete",
            headers={
                "Cookie": "mb_access=access-token; mb_csrf=csrf-token",
                "X-CSRF-Token": "csrf-token",
            },
        )

    assert response.status_code == 200
    assert response.json()["completed_at"].startswith("2026-08-31")


def test_authenticated_delete_removes_auth_identity_and_clears_session():
    account = _account()
    deleted = []
    fake_service = SimpleNamespace(
        current_account=lambda _token: account,
        delete_account=lambda value: deleted.append(value.id),
    )
    settings = _settings(cache_db_path="/tmp/movieboxd-test-cache.sqlite3")
    with (
        patch("app.main.get_settings", return_value=settings),
        patch("app.main._auth_service", return_value=fake_service),
        patch("app.main._enforce_delete_rate_limit", new=AsyncMock()),
        patch("app.main.Cache", return_value=object()),
        patch("app.main.SupabaseCache", return_value=object()),
        patch("app.main._delete_cached_user_data", return_value=True),
        patch("supabase.create_client", return_value=object()),
        TestClient(main.app, base_url="https://testserver") as client,
    ):
        response = client.request(
            "DELETE",
            "/api/data",
            json={"username": "film_fan"},
            headers={
                "Cookie": "mb_access=access-token; mb_csrf=csrf-token",
                "X-CSRF-Token": "csrf-token",
            },
        )

    assert response.status_code == 200
    assert deleted == [account.id]
    cookies = response.headers.get_list("set-cookie")
    assert any(item.startswith("mb_access=") and "Max-Age=0" in item for item in cookies)


def test_readiness_reports_schema_state_without_exposing_details():
    fake_service = SimpleNamespace(check_schema=lambda: True)
    main._readiness_cache.update(checked_at=0.0, ready=False)
    with (
        patch("app.main.get_settings", return_value=_settings()),
        patch("app.main._auth_service", return_value=fake_service),
        TestClient(main.app) as client,
    ):
        response = client.get("/api/readiness")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ready",
        "auth_configured": True,
        "schema_ready": True,
    }


def test_readiness_is_503_when_auth_is_not_configured():
    with (
        patch("app.main.get_settings", return_value=SimpleNamespace(has_auth=False)),
        TestClient(main.app) as client,
    ):
        response = client.get("/api/readiness")

    assert response.status_code == 503
    assert response.json()["schema_ready"] is False


def test_refreshing_blend_forces_a_new_comparison():
    account = _account()
    fake_service = SimpleNamespace(current_account=lambda _token: account)
    computed = {"request_id": "request-123", "score": 86, "cached": False}
    compute = AsyncMock(return_value=computed)
    with (
        patch("app.main.get_settings", return_value=_settings()),
        patch("app.main._auth_service", return_value=fake_service),
        patch("app.main._enforce_heavy_rate_limit", new=AsyncMock()),
        patch("app.main._cancel_blend_background_tasks", new=AsyncMock()),
        patch("app.main._accepted_blend_single_flight", new=compute),
        TestClient(main.app, base_url="https://testserver") as client,
    ):
        response = client.post(
            "/api/blends/request-123/refresh",
            headers={
                "Cookie": "mb_access=access-token; mb_csrf=csrf-token",
                "X-CSRF-Token": "csrf-token",
            },
        )

    assert response.status_code == 200
    assert response.json() == {"status": "refreshed", "result": computed}
    assert compute.await_args.kwargs["force_recompute"] is True


def test_deleting_blend_removes_the_shared_record():
    account = _account()
    deleted = []
    fake_service = SimpleNamespace(
        current_account=lambda _token: account,
        delete_blend=lambda _account, request_id: deleted.append(request_id),
    )
    with (
        patch("app.main.get_settings", return_value=_settings()),
        patch("app.main._auth_service", return_value=fake_service),
        patch("app.main._cancel_blend_background_tasks", new=AsyncMock()),
        TestClient(main.app, base_url="https://testserver") as client,
    ):
        response = client.delete(
            "/api/blends/request-123",
            headers={
                "Cookie": "mb_access=access-token; mb_csrf=csrf-token",
                "X-CSRF-Token": "csrf-token",
            },
        )

    assert response.status_code == 200
    assert response.json() == {"ok": True, "request_id": "request-123"}
    assert deleted == ["request-123"]
