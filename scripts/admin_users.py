#!/usr/bin/env python3
"""Print an aggregate report for registered Movieboxd users.

The command is intentionally local-only and uses the Supabase service-role key
from ``.env.local``/the environment. It never exposes passwords, auth tokens,
raw event metadata or film rows.

Usage::

    python -m scripts.admin_users
    python -m scripts.admin_users --username enesaysu --json
    python -m scripts.admin_users --include-non-active

Run the latest ``supabase/schema.sql`` first; it creates the protected report
function and activity-event table used here.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime

from app.config import get_settings


def _normalise(value: str) -> str:
    return value.strip().lstrip("@").lower()


def _fetch_report(*, include_non_active: bool) -> list[dict]:
    settings = get_settings()
    if not settings.has_supabase:
        raise RuntimeError("SUPABASE_URL / SUPABASE_KEY yapılandırılmamış.")
    from supabase import create_client

    client = create_client(settings.supabase_url, settings.supabase_key)
    result = client.rpc(
        "admin_user_activity_report",
        {"p_include_non_active": bool(include_non_active)},
    ).execute()
    rows = result.data or []
    if isinstance(rows, dict):
        rows = [rows]
    return [dict(row) for row in rows]


def _short_date(value) -> str:
    if not value:
        return "-"
    text = str(value)
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).strftime(
            "%Y-%m-%d %H:%M"
        )
    except ValueError:
        return text[:16]


def _print_table(rows: list[dict]) -> None:
    if not rows:
        print("Kayıtlı kullanıcı bulunamadı.")
        return
    columns = [
        ("username", "KULLANICI"),
        ("account_status", "DURUM"),
        ("created_at", "KAYIT"),
        ("scan", "TARAMA"),
        ("watched_count", "İZLENEN"),
        ("watchlist_count", "WATCHLIST"),
        ("blend_summary", "BLEND GÖNDER/AL/TAMAM"),
        ("recommendations", "ÖNERİ"),
        ("random_attempts", "RASTGELE"),
        ("profile_sync_requests", "SENK."),
        ("login_count", "GİRİŞ"),
        ("last_activity_at", "SON AKTİVİTE"),
    ]
    rendered: list[list[str]] = []
    for row in rows:
        total = int(row.get("scan_total") or 0)
        processed = int(row.get("scan_processed") or 0)
        attempts = int(row.get("recommendation_attempts") or 0)
        successes = int(row.get("recommendation_successes") or 0)
        rendered.append([
            str(row.get("username") or "-"),
            str(row.get("account_status") or "-"),
            _short_date(row.get("created_at")),
            f"{processed}/{total}" if total else str(processed),
            str(row.get("watched_count") or 0),
            str(row.get("watchlist_count") or 0),
            (
                f"{int(row.get('blend_requests_sent') or 0)}/"
                f"{int(row.get('blend_requests_received') or 0)}/"
                f"{int(row.get('completed_blends') or 0)}"
            ),
            f"{successes}/{attempts}",
            str(row.get("random_attempts") or 0),
            str(row.get("profile_sync_requests") or 0),
            str(row.get("login_count") or 0),
            _short_date(row.get("last_activity_at")),
        ])
    widths = [max(len(header), *(len(row[i]) for row in rendered)) for i, (_key, header) in enumerate(columns)]
    print("  ".join(header.ljust(widths[i]) for i, (_key, header) in enumerate(columns)))
    print("  ".join("-" * width for width in widths))
    for row in rendered:
        print("  ".join(value.ljust(widths[i]) for i, value in enumerate(row)))
    print(
        "\nÖNERİ sütunu: başarılı/toplam deneme. "
        "BLEND sütunu: gönderilen/alınan/tamamlanan. "
        "TARAMA: işlenen/toplam film."
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--username", action="append", default=[], help="Yalnızca bu kullanıcı(lar)")
    parser.add_argument(
        "--include-non-active",
        action="store_true",
        help="disabled/pending/anonymous hesapları da dahil et",
    )
    parser.add_argument("--json", action="store_true", dest="as_json", help="JSON çıktı ver")
    args = parser.parse_args()
    try:
        rows = _fetch_report(include_non_active=args.include_non_active)
    except Exception as exc:  # noqa: BLE001 - CLI should present a useful error
        print(
            "Rapor alınamadı. Supabase migration'ını çalıştırdığından emin ol: "
            f"{exc}",
            file=sys.stderr,
        )
        return 1

    requested = {_normalise(value) for value in args.username if _normalise(value)}
    if requested:
        rows = [row for row in rows if _normalise(str(row.get("username", ""))) in requested]
    if args.as_json:
        print(json.dumps(rows, ensure_ascii=False, indent=2, default=str))
    else:
        _print_table(rows)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
