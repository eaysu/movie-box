#!/usr/bin/env python3
"""Open the letterbox on accounts that never chose either way.

The letterbox used to be off by default, so most members have it closed simply
because that was the default, not because they decided to be unreachable. This
opens it once for active accounts.

It is deliberately a script and not a line in schema.sql: the schema is applied
repeatedly, and a bulk UPDATE there would keep re-opening the letterbox of
someone who deliberately closed it.

    python -m scripts.open_letterboxes           # list who would change
    python -m scripts.open_letterboxes --apply
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


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="Değişikliği uygula")
    args = parser.parse_args()

    try:
        client = _client()
    except Exception as exc:  # noqa: BLE001 - CLI should present a useful error
        print(f"Bağlanılamadı: {exc}", file=sys.stderr)
        return 1

    closed = client.table("users").select("id,username").eq(
        "account_status", "active"
    ).eq("letter_receiving_enabled", False).execute().data or []
    if not closed:
        print("Kutusu kapalı aktif hesap yok.")
        return 0

    print(f"{len(closed)} hesabın mektup kutusu kapalı:")
    for row in closed:
        print(f"  @{row['username']}")
    if not args.apply:
        print("\nUygulamak için: python -m scripts.open_letterboxes --apply")
        return 0

    now = datetime.now(timezone.utc).isoformat()
    for row in closed:
        client.table("users").update(
            {"letter_receiving_enabled": True, "updated_at": now}
        ).eq("id", row["id"]).execute()
        try:
            client.table("user_activity_events").insert({
                "user_id": row["id"],
                "event_type": "letter_receiving_changed",
                "metadata": {"enabled": True, "reason": "default_opened"},
            }).execute()
        except Exception:
            pass
    print(f"\n{len(closed)} hesabın kutusu açıldı; profilinden kapatabilirler.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
