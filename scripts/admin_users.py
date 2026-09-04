#!/usr/bin/env python3
"""Print an aggregate report for registered Movieboxd users.

The command is intentionally local-only and uses the Supabase service-role key
from ``.env.local``/the environment. It never exposes passwords, auth tokens,
raw event metadata or film rows. Letters are reported as counts only: bodies and
film gifts are end-to-end encrypted and unreadable to the server, and recipients
are deliberately left out of the report.

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
from datetime import datetime, timedelta, timezone

try:  # Python 3.9+ with tzdata available
    from zoneinfo import ZoneInfo

    REPORT_TZ = ZoneInfo("Europe/Istanbul")
except Exception:  # pragma: no cover - fixed +03:00 is correct for Türkiye
    REPORT_TZ = timezone(timedelta(hours=3))

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


def _parse_time(value) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _short_date(value) -> str:
    """Supabase stores UTC; the report is read locally, so print Istanbul time."""
    if not value:
        return "-"
    parsed = _parse_time(value)
    if parsed is None:
        return str(value)[:16]
    return parsed.astimezone(REPORT_TZ).strftime("%Y-%m-%d %H:%M")


def _activity_key(row: dict) -> datetime:
    """Newest signal of life first: activity, then last sync, then registration."""
    for field in ("last_activity_at", "profile_synced_at", "created_at"):
        parsed = _parse_time(row.get(field))
        if parsed is not None:
            return parsed
    return datetime.min.replace(tzinfo=timezone.utc)


def _sort_by_activity(rows: list[dict]) -> list[dict]:
    return sorted(rows, key=_activity_key, reverse=True)


def _short_day(value) -> str:
    """Date-only rendering, used where the hour would only cost table width."""
    return _short_date(value)[:10]


def _flag(value, on: str, off: str) -> str:
    if value is None:
        return "-"
    return on if bool(value) else off


def _has_letter_data(rows: list[dict]) -> bool:
    """False when the deployed report function predates the letter columns."""
    return any("letters_sent" in row for row in rows)


def _print_table(rows: list[dict]) -> None:
    if not rows:
        print("Kayıtlı kullanıcı bulunamadı.")
        return
    headers = [
        "#",
        "KULLANICI",
        "DURUM",
        "SİNEFİL",
        "M.KUTU",
        "MEKTUP",
        "SON MEKTUP",
        "KAYIT",
        "TARAMA",
        "İZLENEN",
        "WATCHLIST",
        "BLEND",
        "ÖNERİ",
        "RASTGELE",
        "SENK.",
        "GİRİŞ",
        "SON AKTİVİTE",
    ]
    rendered: list[list[str]] = []
    for index, row in enumerate(rows, start=1):
        total = int(row.get("scan_total") or 0)
        processed = int(row.get("scan_processed") or 0)
        attempts = int(row.get("recommendation_attempts") or 0)
        successes = int(row.get("recommendation_successes") or 0)
        if "letters_sent" in row:
            letters = (
                f"{int(row.get('letters_sent') or 0)}/"
                f"{int(row.get('letters_received') or 0)}/"
                f"{int(row.get('letters_unread') or 0)}"
            )
        else:
            letters = "-"
        rendered.append([
            str(index),
            str(row.get("username") or "-"),
            str(row.get("account_status") or "-"),
            _flag(row.get("discoverable"), "online", "offline"),
            _flag(row.get("letter_receiving_enabled"), "açık", "kapalı"),
            letters,
            _short_day(row.get("last_letter_at")),
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
    widths = [
        max(len(header), *(len(row[i]) for row in rendered))
        for i, header in enumerate(headers)
    ]
    print("  ".join(header.ljust(widths[i]) for i, header in enumerate(headers)))
    print("  ".join("-" * width for width in widths))
    for row in rendered:
        print("  ".join(value.ljust(widths[i]) for i, value in enumerate(row)))
    _print_summary(rows)


def _print_summary(rows: list[dict]) -> None:
    print(
        "\nSıralama: en son aktif olandan en eskiye. "
        "SİNEFİL: Sinefil Sineması görünürlüğü. "
        "M.KUTU: mektup alma tercihi. "
        "MEKTUP: gönderilen/alınan/okunmamış. "
        "BLEND: gönderilen/alınan/tamamlanan. "
        "ÖNERİ: başarılı/toplam deneme. "
        "TARAMA: işlenen/toplam film."
    )
    online = sum(1 for row in rows if row.get("discoverable"))
    receiving = sum(1 for row in rows if row.get("letter_receiving_enabled"))
    print(
        f"Toplam {len(rows)} kullanıcı · Sinefil Sineması'nda {online} online, "
        f"{len(rows) - online} offline · mektup kutusu açık {receiving} kişi"
    )
    if not _has_letter_data(rows):
        print(
            "Mektup ve görünürlük sütunları boş: güncel supabase/schema.sql "
            "dosyasını SQL Editor'da çalıştır."
        )
        return
    senders = [row for row in rows if int(row.get("letters_sent") or 0) > 0]
    total_letters = sum(int(row.get("letters_sent") or 0) for row in rows)
    unread = sum(int(row.get("letters_unread") or 0) for row in rows)
    if not senders:
        print("Mektup: henüz kimse mektup yollamadı.")
        return
    top = sorted(senders, key=lambda row: int(row.get("letters_sent") or 0), reverse=True)
    detail = ", ".join(
        f"{row.get('username')} ({int(row.get('letters_sent') or 0)})" for row in top[:5]
    )
    print(
        f"Mektup: {len(senders)} kullanıcı toplam {total_letters} mektup yolladı · "
        f"{unread} mektup henüz okunmadı · en çok yollayanlar: {detail}"
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
    # The report function already orders by activity; sorting here keeps the
    # order correct against an older deployed function too.
    rows = _sort_by_activity(rows)
    if args.as_json:
        print(json.dumps(rows, ensure_ascii=False, indent=2, default=str))
    else:
        _print_table(rows)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
