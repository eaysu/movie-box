#!/usr/bin/env python3
"""Seed the follow graph from the members' existing Letterboxd follow lists.

A social graph cannot be built from nothing with 126 accounts: nobody searches
for strangers. But these people already follow each other on Letterboxd, and
that graph is public. This copies the part of it that exists inside Movieboxd.

Four rules the copy obeys:

* **One direction only.** If A follows B on Letterboxd, A follows B here. It
  never invents a mutual relationship that does not exist.
* **Only registered members.** Names not in `users` are ignored; nobody is
  invited or created.
* **Never re-added.** Rows are marked `source='letterboxd'` and existing rows
  are left alone, so a member who unfollows is not followed again on the next
  run.
* **A failed read is not an empty list.** Letterboxd answers a long run with
  403s. A member whose page could not be read is reported as a failure and
  left for a later run — never recorded as following nobody.
* **The whole list, not the first page of it.** Members here follow hundreds of
  people; reading only five pages lost a fifth of the matches in practice.

Rows are written per member rather than in one batch at the end, so a run cut
short by rate limiting keeps everything it already earned.

    python -m scripts.seed_follows                 # show what would be created
    python -m scripts.seed_follows --apply
    python -m scripts.seed_follows --user enesaysu --apply
    python -m scripts.seed_follows --apply --pause 6   # gentler on Letterboxd
"""

from __future__ import annotations

import argparse
import asyncio
import sys

from app.config import get_settings
from app.scraper import scrape_following


def _client():
    settings = get_settings()
    if not settings.has_supabase:
        raise RuntimeError("SUPABASE_URL / SUPABASE_KEY yapılandırılmamış.")
    from supabase import create_client

    return create_client(settings.supabase_url, settings.supabase_key)


def _members(client) -> dict[str, int]:
    return {
        row["username"]: int(row["id"])
        for row in (
            client.table("users").select("id,username")
            .eq("account_status", "active").execute().data or []
        )
    }


def _existing_pairs(client) -> set[tuple[int, int]]:
    return {
        (int(row["follower_id"]), int(row["followee_id"]))
        for row in (
            client.table("follows").select("follower_id,followee_id").execute().data or []
        )
    }


def _write(client, follower_id: int, followee_ids: list[int]) -> None:
    rows = [
        {"follower_id": follower_id, "followee_id": followee_id, "source": "letterboxd"}
        for followee_id in followee_ids
    ]
    for start in range(0, len(rows), 200):
        client.table("follows").insert(rows[start:start + 200]).execute()


async def run(
    client, usernames: list[str], *, apply: bool, pause: float, max_pages: int,
) -> int:
    members = _members(client)
    existing = _existing_pairs(client)
    targets = usernames or sorted(members)
    created = failed = matched = 0

    for index, username in enumerate(targets, start=1):
        prefix = f"  [{index}/{len(targets)}] @{username}"
        if username not in members:
            print(f"{prefix}: kayıtlı değil, atlandı", flush=True)
            continue

        following = await scrape_following(username, max_pages=max_pages)
        if following is None:
            failed += 1
            print(f"{prefix}: sayfa okunamadı (403/gizli) — sonraki koşuya bırakıldı", flush=True)
            # Back off harder after a refusal; hammering earns more of them.
            await asyncio.sleep(max(pause, 1.0) * 4)
            continue

        overlap = [name for name in following if name in members and name != username]
        matched += len(overlap)
        fresh = [
            members[name] for name in overlap
            if (members[username], members[name]) not in existing
        ]
        for name in overlap:
            existing.add((members[username], members[name]))
        if apply and fresh:
            _write(client, members[username], fresh)
        created += len(fresh)
        print(
            f"{prefix}: Letterboxd'da {len(following)} takip · burada {len(overlap)} "
            f"eşleşme · {len(fresh)} yeni",
            flush=True,
        )
        if index < len(targets):
            await asyncio.sleep(pause)

    verb = "oluşturuldu" if apply else "oluşturulacak"
    print(f"\n{matched} eşleşme, {created} yeni takip {verb} (mevcutlar korundu).")
    if failed:
        print(
            f"{failed} hesabın sayfası okunamadı. Aynı komutu tekrar çalıştırmak "
            "yalnız eksikleri tamamlar; bitenler atlanır."
        )
    if not apply:
        print("Uygulamak için: python -m scripts.seed_follows --apply")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--user", action="append", default=[], help="Yalnız bu hesap(lar)")
    parser.add_argument("--apply", action="store_true", help="Takipleri oluştur")
    parser.add_argument(
        "--pause", type=float, default=3.0,
        help="Hesaplar arası bekleme (saniye, varsayılan 3)",
    )
    parser.add_argument(
        "--max-pages", type=int, default=20,
        help="Takip listesinde okunacak azami sayfa (25 kişi/sayfa, varsayılan 20)",
    )
    args = parser.parse_args()

    try:
        client = _client()
    except Exception as exc:  # noqa: BLE001 - CLI should present a useful error
        print(f"Bağlanılamadı: {exc}", file=sys.stderr)
        return 1

    usernames = [u.strip().lstrip("@").lower() for u in args.user if u.strip()]
    print("Letterboxd takip listeleri okunuyor…", flush=True)
    return asyncio.run(run(
        client, usernames, apply=args.apply, pause=args.pause,
        max_pages=args.max_pages,
    ))


if __name__ == "__main__":
    raise SystemExit(main())
