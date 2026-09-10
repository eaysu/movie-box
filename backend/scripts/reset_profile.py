#!/usr/bin/env python3
"""Reset a registered profile back to a fresh state for onboarding testing.

Soft reset (default): keeps the account + Letterboxd ownership verification, but
wipes every regenerable artefact so the next login replays onboarding —
  * deletes taste_profiles / profile_favorites / user_watched_films /
    profile_sync_jobs rows for the user
  * sets users.profile_sync_status = 'pending' (profile_synced_at = NULL)
  * purges the Supabase tmdb_cache rows that hold the user's scraped film lists
    and cached recommendations

Hard reset (--hard): additionally removes the account row and its Supabase Auth
identity, so the next run has to re-register and re-verify the bio code.

Connects to Supabase with the service-role key from .env.local / the environment.

Usage:
    python -m scripts.reset_profile enesaysu
    python -m scripts.reset_profile enesaysu ayswaitt          # several at once
    python -m scripts.reset_profile enesaysu --hard            # full wipe

After running, open the site in a fresh browser tab (or private window) so
sessionStorage['mb_onboarded'] is empty, then log in — onboarding replays.
"""

import argparse
from datetime import datetime, timezone

from app.config import get_settings
from app.database import SupabaseCache
from app.main import _delete_cached_user_data

_PROFILE_TABLES = (
    "taste_profiles",
    "profile_favorites",
    "user_watched_films",
    "profile_sync_jobs",
)


def _norm(username: str) -> str:
    return username.strip().lstrip("@").lower()


def _reset_one(client, username: str, *, hard: bool) -> None:
    row = (
        client.table("users")
        .select("id,auth_user_id,account_status,profile_sync_status")
        .eq("username", username)
        .limit(1)
        .execute()
    ).data
    if not row:
        print(f"  {username}: no account row — nothing to reset")
        return
    user = row[0]
    uid = user["id"]

    for table in _PROFILE_TABLES:
        deleted = (
            client.table(table).delete().eq("user_id", uid).execute()
        ).data or []
        print(f"  {username}: {table} -{len(deleted)}")

    cache_ok = _delete_cached_user_data(SupabaseCache(client), username)
    print(f"  {username}: tmdb_cache purge {'ok' if cache_ok else 'partial'}")

    if hard:
        auth_id = user.get("auth_user_id")
        client.table("users").delete().eq("id", uid).execute()
        if auth_id:
            try:
                client.auth.admin.delete_user(auth_id)
                print(f"  {username}: auth identity removed")
            except Exception as exc:  # noqa: BLE001 - best effort
                print(f"  {username}: auth identity NOT removed ({exc})")
        print(f"  {username}: account GONE -> register again (bio code needed)")
        return

    client.table("users").update(
        {
            "profile_sync_status": "pending",
            "profile_synced_at": None,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
    ).eq("id", uid).execute()
    print(
        f"  {username}: profile wiped, status -> pending. "
        "Account kept -> LOG IN (do not register); onboarding replays."
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("usernames", nargs="+")
    parser.add_argument(
        "--hard",
        action="store_true",
        help="also delete the account + auth identity (forces re-registration)",
    )
    args = parser.parse_args()

    settings = get_settings()
    if not settings.has_supabase:
        print("SUPABASE_URL / SUPABASE_KEY not configured — cannot reset.")
        return 1

    from supabase import create_client

    client = create_client(settings.supabase_url, settings.supabase_key)
    for username in (_norm(u) for u in args.usernames):
        print(f"{username}:")
        _reset_one(client, username, hard=args.hard)
    print("done.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
