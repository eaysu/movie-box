import asyncio
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

from app.auth import Account
from app.enrich import EnrichedFilm
from app.main import BLEND_VERSION, _compute_accepted_blend


def _account(user_id: int, username: str) -> Account:
    return Account(
        id=user_id,
        auth_user_id=f"auth-{user_id}",
        username=username,
        display_name=username.title(),
        profile_sync_status="ready",
    )


def test_accepted_blend_is_computed_and_persisted_once():
    actor = _account(1, "first_user")
    first = actor
    second = _account(2, "second_user")
    watched = [
        EnrichedFilm(
            title="Shared Film",
            slug="shared-film",
            genres=["Drama"],
            director="Shared Director",
            keywords=["memory"],
        )
    ]
    watchlist = [EnrichedFilm(title="Next Film", slug="next-film")]

    async def load(_username, list_type, **_kwargs):
        return (watched if list_type == "watched" else watchlist), True

    service = SimpleNamespace(
        get_blend_result=Mock(return_value=None),
        get_blend_participants=Mock(return_value=({}, first, second)),
        save_blend_result=Mock(return_value="result-1"),
    )
    settings = SimpleNamespace(
        has_tmdb=False,
        scrape_delay=0,
        watched_max_pages=1,
        watched_film_limit=100,
        scrape_max_retries=1,
        scrape_max_pages=1,
        watchlist_film_limit=100,
    )
    with (
        patch("app.main.get_settings", return_value=settings),
        patch("app.main._make_cache", return_value=(None, object())),
        patch("app.main._make_persistent_cache", return_value=object()),
        patch("app.main._load_user_films", new=AsyncMock(side_effect=load)),
    ):
        result = asyncio.run(
            _compute_accepted_blend(actor, "request-1", service)
        )

    assert result["result_id"] == "result-1"
    assert result["username1"] == "first_user"
    assert result["username2"] == "second_user"
    assert result["score"] >= 99
    service.save_blend_result.assert_called_once()
    assert service.save_blend_result.call_args.kwargs["algorithm_version"] == BLEND_VERSION


def test_existing_blend_result_short_circuits_external_work():
    actor = _account(1, "first_user")
    service = SimpleNamespace(
        get_blend_result=Mock(
            return_value={"result": {"score": 77, "username1": "first_user"}}
        )
    )
    load = AsyncMock()
    with patch("app.main._load_user_films", new=load):
        result = asyncio.run(
            _compute_accepted_blend(actor, "request-1", service)
        )

    assert result == {
        "score": 77,
        "username1": "first_user",
        "request_id": "request-1",
        "cached": True,
    }
    load.assert_not_awaited()


def test_schema_contains_atomic_consent_guards():
    schema = (Path(__file__).parents[1] / "supabase" / "schema.sql").read_text()
    assert "idx_blend_requests_pending_unordered_pair" in schema
    assert "pg_advisory_xact_lock" in schema
    assert "v_request.recipient_user_id <> p_recipient_user_id" in schema
    assert "status = 'accepted'" in schema
    assert "CREATE OR REPLACE FUNCTION public.save_blend_result" in schema
    assert "CREATE TABLE IF NOT EXISTS public.user_blocks" in schema
    assert "CREATE TABLE IF NOT EXISTS public.user_reports" in schema
    assert "RAISE EXCEPTION 'blend_user_blocked'" in schema
