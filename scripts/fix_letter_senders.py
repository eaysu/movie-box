#!/usr/bin/env python3
"""Open the letterbox of members who sent a letter while theirs was closed.

Sending now requires an open letterbox of your own, because a letter from a
closed account is a channel the recipient cannot answer. Accounts that sent
before that rule existed are stuck in exactly that state: their letter is out
there and no reply can reach them.

This repairs those accounts. It is deliberately dry-run by default, prints
every account it would touch, and records an activity event for each change so
the reason is traceable later. The member can close their letterbox again from
their profile at any time.

Usage::

    python -m scripts.fix_letter_senders            # list who is affected
    python -m scripts.fix_letter_senders --apply    # open their letterboxes
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone

from app.config import get_settings


def _client():
    settings = get_settings()
    if not settings.has_supabase:
        raise RuntimeError("SUPABASE_URL / SUPABASE_KEY yapılandırılmamış.")
    from supabase import create_client

    return create_client(settings.supabase_url, settings.supabase_key)


def find_affected(client) -> list[dict]:
    """Active accounts that have sent a letter but cannot receive one."""
    letters = client.table("cinephile_letters").select("sender_user_id").execute().data or []
    senders = sorted({int(row["sender_user_id"]) for row in letters if row.get("sender_user_id")})
    if not senders:
        return []
    counts: dict[int, int] = {}
    for row in letters:
        key = int(row["sender_user_id"])
        counts[key] = counts.get(key, 0) + 1
    users = client.table("users").select(
        "id,username,account_status,letter_receiving_enabled"
    ).in_("id", senders).execute().data or []
    return [
        {**user, "sent": counts.get(int(user["id"]), 0)}
        for user in users
        if user.get("account_status") == "active"
        and not user.get("letter_receiving_enabled")
    ]


def apply_fix(client, accounts: list[dict]) -> int:
    now = datetime.now(timezone.utc).isoformat()
    changed = 0
    for account in accounts:
        client.table("users").update(
            {"letter_receiving_enabled": True, "updated_at": now}
        ).eq("id", account["id"]).execute()
        # Leave a trace of why this account's setting changed without them
        # touching it.
        try:
            client.table("user_activity_events").insert({
                "user_id": account["id"],
                "event_type": "letter_receiving_changed",
                "metadata": {"enabled": True, "reason": "sent_before_rule"},
            }).execute()
        except Exception:
            pass
        changed += 1
    return changed


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--apply", action="store_true", help="Değişikliği uygula (varsayılan: yalnız listele)"
    )
    args = parser.parse_args()

    try:
        client = _client()
    except Exception as exc:  # noqa: BLE001 - CLI should present a useful error
        print(f"Bağlanılamadı: {exc}", file=sys.stderr)
        return 1

    accounts = find_affected(client)
    if not accounts:
        print("Mektup yollayıp kutusu kapalı kalan hesap yok.")
        return 0

    print(f"{len(accounts)} hesabın kutusu kapalı olmasına rağmen mektup yollamış:\n")
    for account in accounts:
        print(f"  @{account['username']}  (gönderdiği mektup: {account['sent']})")

    if not args.apply:
        print("\nUygulamak için: python -m scripts.fix_letter_senders --apply")
        return 0

    changed = apply_fix(client, accounts)
    print(f"\n{changed} hesabın mektup kutusu açıldı; profilinden kapatabilirler.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
