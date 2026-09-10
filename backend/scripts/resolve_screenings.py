#!/usr/bin/env python3
"""Inspect and repair the cinema bulletin's unmatched programme lines.

Local-only, service-role, in the shape of ``scripts.admin_users``. A venue line
the automatic matcher could not tie to a film stays visible here instead of
being guessed at, so a wrong film never reaches a member's card.

Usage::

    python -m scripts.resolve_screenings                      # list the queue
    python -m scripts.resolve_screenings --venues             # venue health
    python -m scripts.resolve_screenings --map "Sonbahar Sonatı=4174"
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime, timedelta, timezone

try:
    from zoneinfo import ZoneInfo

    REPORT_TZ = ZoneInfo("Europe/Istanbul")
except Exception:  # pragma: no cover - fixed +03:00 is correct for Türkiye
    REPORT_TZ = timezone(timedelta(hours=3))

from app.config import get_settings


def _client():
    settings = get_settings()
    if not settings.has_supabase:
        raise RuntimeError("SUPABASE_URL / SUPABASE_KEY yapılandırılmamış.")
    from supabase import create_client

    return create_client(settings.supabase_url, settings.supabase_key)


def _short(value) -> str:
    if not value:
        return "-"
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return str(value)[:16]
    if not parsed.tzinfo:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(REPORT_TZ).strftime("%Y-%m-%d %H:%M")


def list_venues(client) -> int:
    rows = client.table("venues").select(
        "slug,name,city,kind,active,last_ok_at,last_error"
    ).order("kind").execute().data or []
    if not rows:
        print("Kayıtlı mekân yok.")
        return 0
    width = max(len(row["slug"]) for row in rows)
    for row in rows:
        state = "açık" if row.get("active") else "kapalı"
        error = (row.get("last_error") or "").strip()
        print(
            f"{row['slug'].ljust(width)}  {state:6}  {row.get('kind', ''):9}  "
            f"son başarı: {_short(row.get('last_ok_at'))}"
            + (f"  HATA: {error[:80]}" if error else "")
        )
    return 0


def list_unresolved(client, limit: int) -> int:
    rows = client.table("screenings").select(
        "id,title_raw,year,match_status,updated_at,venues(slug,name)"
    ).neq("match_status", "matched").order("updated_at", desc=True).limit(limit).execute().data or []
    if not rows:
        print("Eşleşmeyen gösterim yok.")
        return 0
    print(f"{len(rows)} eşleşmemiş satır (en yeniden eskiye):\n")
    for row in rows:
        venue = (row.get("venues") or {}).get("slug", "?")
        year = row.get("year") or "----"
        print(
            f"  [{row['match_status']:10}] {row['title_raw']} ({year})"
            f"  · {venue} · {_short(row.get('updated_at'))}"
        )
    print(
        '\nBağlamak için:  python -m scripts.resolve_screenings --map "Başlık=TMDB_ID"'
    )
    return 0


def apply_mapping(client, mapping: str) -> int:
    if "=" not in mapping:
        print('Biçim: --map "Başlık=TMDB_ID"', file=sys.stderr)
        return 2
    title, _, raw_id = mapping.rpartition("=")
    title = title.strip()
    try:
        tmdb_id = int(raw_id.strip())
    except ValueError:
        print("TMDb id bir tam sayı olmalı.", file=sys.stderr)
        return 2

    updated = client.table("screenings").update(
        {"tmdb_id": tmdb_id, "match_status": "matched"}
    ).eq("title_raw", title).neq("match_status", "matched").execute().data or []
    if not updated:
        print(f"'{title}' için eşleşmemiş satır bulunamadı.")
        return 1
    print(f"'{title}' → TMDb {tmdb_id} olarak {len(updated)} satırda işaretlendi.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--venues", action="store_true", help="Mekân sağlık durumu")
    parser.add_argument("--limit", type=int, default=50, help="Listelenecek satır sayısı")
    parser.add_argument("--map", dest="mapping", help='"Başlık=TMDB_ID" olarak elle bağla')
    args = parser.parse_args()

    try:
        client = _client()
    except Exception as exc:  # noqa: BLE001 - CLI should present a useful error
        print(f"Bağlanılamadı: {exc}", file=sys.stderr)
        return 1

    if args.venues:
        return list_venues(client)
    if args.mapping:
        return apply_mapping(client, args.mapping)
    return list_unresolved(client, args.limit)


if __name__ == "__main__":
    raise SystemExit(main())
