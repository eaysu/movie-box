import asyncio
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

from app.auth import Account, AuthService
from app.enrich import EnrichedFilm
from app.main import (
    BLEND_VERSION,
    _complete_blend_profile_metadata,
    _complete_blend_watchlists,
    _compute_accepted_blend,
    _enriched_from_watched_rows,
)


def _account(user_id: int, username: str) -> Account:
    return Account(
        id=user_id,
        auth_user_id=f"auth-{user_id}",
        username=username,
        display_name=username.title(),
        avatar_url=f"https://a.ltrbxd.com/{username}.jpg",
        profile_sync_status="ready",
    )


def test_accepted_blend_is_computed_and_persisted_once():
    actor = _account(1, "first_user")
    first = actor
    second = _account(2, "second_user")
    watched_rows = [
        {
            "film_slug": "shared-film",
            "title": "Shared Film",
            "release_year": 2020,
            "genres": ["Drama"],
            "director": "Shared Director",
            "keywords": ["memory"],
            "details_loaded": True,
            "watched_rank": 0,
        }
    ]
    watchlist = [EnrichedFilm(title="Next Film", slug="next-film")]

    async def load(_username, list_type, **_kwargs):
        return watchlist, True

    service = SimpleNamespace(
        get_blend_result=Mock(return_value=None),
        get_blend_participants=Mock(return_value=({}, first, second)),
        get_watched_films=Mock(return_value=watched_rows),
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
    assert result["avatar_url1"].endswith("/first_user.jpg")
    assert result["avatar_url2"].endswith("/second_user.jpg")
    assert result["score"] >= 99
    assert result["watchlist_pending"] is True
    service.save_blend_result.assert_called_once()
    assert service.save_blend_result.call_args.kwargs["algorithm_version"] == BLEND_VERSION


def test_existing_blend_result_short_circuits_external_work():
    actor = _account(1, "first_user")
    second = _account(2, "second_user")
    service = SimpleNamespace(
        get_blend_participants=Mock(return_value=({}, actor, second)),
        get_blend_result=Mock(
            return_value={
                "algorithm_version": BLEND_VERSION,
                "result": {"score": 77, "username1": "first_user"},
            }
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
        "avatar_url1": "https://a.ltrbxd.com/first_user.jpg",
        "avatar_url2": "https://a.ltrbxd.com/second_user.jpg",
        "request_id": "request-1",
        "cached": True,
    }
    load.assert_not_awaited()


def test_blend_profile_uses_every_active_db_row_without_recent_limit():
    rows = [
        {
            "film_slug": f"film-{index}",
            "title": f"Film {index}",
            "watched_rank": index,
            "details_loaded": True,
        }
        for index in range(137)
    ]

    films = _enriched_from_watched_rows(rows)

    assert len(films) == 137
    assert films[0].slug == "film-0"
    assert films[-1].slug == "film-136"


def test_blend_completes_metadata_for_every_incomplete_row_and_persists_it():
    films = [
        EnrichedFilm(title=f"Film {index}", slug=f"film-{index}")
        for index in range(121)
    ]

    class FakeEnricher:
        async def enrich(self, pending, *, include_details=True):
            assert include_details is True
            assert len(pending) == 121
            return [
                EnrichedFilm(
                    title=film.title,
                    slug=film.slug,
                    tmdb_id=index + 1,
                    genres=["Drama"],
                    director="Director",
                    keywords=["memory"],
                    overview=f"Overview {index}",
                    matched=True,
                    details_loaded=True,
                )
                for index, film in enumerate(pending)
            ]

    service = SimpleNamespace(save_watched_films=Mock(return_value=121))

    completed = asyncio.run(
        _complete_blend_profile_metadata(films, 7, FakeEnricher(), service)
    )

    assert len(completed) == 121
    assert all(film.details_loaded for film in completed)
    assert all(film.overview for film in completed)
    saved = service.save_watched_films.call_args.args[1]
    assert len(saved) == 121
    assert saved[-1]["slug"] == "film-120"


def test_pending_watchlists_complete_in_background_and_update_result():
    actor = _account(1, "first_user")
    second = _account(2, "second_user")
    watched_rows = [
        {
            "film_slug": "shared-film", "title": "Shared Film",
            "watched_rank": 0, "details_loaded": True,
        }
    ]
    watchlist = [EnrichedFilm(title="Next Film", slug="next-film")]
    service = SimpleNamespace(
        get_blend_result=Mock(
            return_value={
                "algorithm_version": BLEND_VERSION,
                "result": {
                    "score": 75,
                    "confidence": {"score": 80},
                    "watchlist_pending": True,
                },
            }
        ),
        get_blend_participants=Mock(return_value=({}, actor, second)),
        get_watched_films=Mock(return_value=watched_rows),
        save_blend_result=Mock(return_value="result-1"),
    )
    settings = SimpleNamespace(
        has_tmdb=False,
        scrape_delay=0,
        scrape_max_retries=1,
        scrape_max_pages=1,
        watchlist_film_limit=100,
    )
    load = AsyncMock(return_value=(watchlist, True))
    with (
        patch("app.main.get_settings", return_value=settings),
        patch("app.main._make_cache", return_value=(None, object())),
        patch("app.main._make_persistent_cache", return_value=object()),
        patch("app.main._load_user_films", new=load),
    ):
        asyncio.run(_complete_blend_watchlists(actor, "request-1", service))

    saved = service.save_blend_result.call_args.args[2]
    assert saved["watchlist_pending"] is False
    assert saved["watchlist_public"] is True
    assert saved["common_watchlist_films"][0]["slug"] == "next-film"


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


def test_delete_blend_checks_participant_then_deletes_shared_request():
    actor = _account(1, "first_user")
    client = Mock()
    delete_query = client.table.return_value.delete.return_value.eq.return_value
    delete_query.execute.return_value = SimpleNamespace(data=[])
    service = AuthService.__new__(AuthService)
    service._service_client = Mock(return_value=client)
    service.get_blend_participants = Mock(return_value=({}, actor, _account(2, "second_user")))
    service._audit = Mock()

    service.delete_blend(actor, "request-1")

    service.get_blend_participants.assert_called_once_with(actor, "request-1")
    client.table.assert_called_with("blend_requests")
    client.table.return_value.delete.return_value.eq.assert_called_with("id", "request-1")
