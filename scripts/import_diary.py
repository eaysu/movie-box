#!/usr/bin/env python3
"""Kayıtlı üyelerin Letterboxd güncesini akışa aktarır.

Akışı açan üye zaten sıradaki taramayı tetikliyor (`_kick_diary_ingest`), yani
zamanla bütün üyeler taranıyor. Bu betik aynı işi elle ve toplu yapar: yeni
başlarken akışı bir kerede doldurmak için.

Üç kural içe aktarmanın kendisinde:

* **Bir kez düşer.** Kaydın kimliği RSS guid'i; `posts.source_key` üzerindeki
  tekil indeks aynı kaydı ikinci kez eklemiyor.
* **Silinen geri gelmez.** Silme yumuşak olduğu için satır ve anahtarı duruyor;
  tekrar çalıştırmak onu diriltmiyor.
* **Sıra izlenme günü.** Akışta kayıt, izlendiği günün tarihiyle yer alıyor.
* **Yalnız yorumlu kayıt.** Cümlesi olmayan izleme kaydı akışa girmiyor; puan
  tek başına okunacak bir şey taşımıyor.

    python -m scripts.import_diary                 # ne olacağını göster
    python -m scripts.import_diary --apply
    python -m scripts.import_diary --user enesaysu --apply
    python -m scripts.import_diary --apply --pause 5
"""

from __future__ import annotations

import argparse
import asyncio
import sys

from app.auth import AuthService
from app.config import get_settings
from app.scraper import scrape_diary_entries


def _service() -> AuthService:
    settings = get_settings()
    if not settings.has_supabase:
        raise RuntimeError("SUPABASE_URL / SUPABASE_KEY yapılandırılmamış.")
    return AuthService(settings)


def _members(service, usernames: list[str]) -> list[dict]:
    rows = (
        service._service_client().table("users").select("id,username")
        .eq("account_status", "active").execute().data or []
    )
    if usernames:
        wanted = set(usernames)
        return [row for row in rows if row["username"] in wanted]
    return sorted(rows, key=lambda row: row["username"])


def _rows_from(entries) -> list[dict]:
    return [
        {
            "source_key": entry.key,
            "film_slug": entry.slug,
            "film_title": entry.title,
            "film_year": entry.year,
            "tmdb_id": entry.tmdb_id,
            "body": entry.review,
            "payload": {
                "rating": entry.rating,
                "rewatch": entry.rewatch,
                "watched_on": entry.watched_on,
            },
            "created_at": f"{entry.watched_on}T12:00:00+00:00",
        }
        for entry in entries
        if entry.slug
    ]


async def run(service, members: list[dict], *, apply: bool, pause: float) -> int:
    total = failed = 0
    for index, member in enumerate(members, start=1):
        username = member["username"]
        prefix = f"  [{index}/{len(members)}] @{username}"
        entries = await scrape_diary_entries(username)
        # `None` okunamadı demek — damgayı atmıyoruz, sıradaki koşu yine dener.
        if entries is None:
            failed += 1
            print(f"{prefix}: günce okunamadı, sonraki koşuya bırakıldı", flush=True)
            await asyncio.sleep(max(pause, 1.0) * 3)
            continue
        rows = _rows_from(entries)
        if apply:
            written = await asyncio.to_thread(
                service.import_diary_entries, int(member["id"]), rows
            )
            await asyncio.to_thread(service.mark_diary_synced, int(member["id"]))
        else:
            written = len(rows)
        total += written
        print(
            f"{prefix}: {len(rows)} kayıt · {written} "
            f"{'eklendi' if apply else 'eklenecek'}",
            flush=True,
        )
        if index < len(members):
            await asyncio.sleep(pause)

    verb = "eklendi" if apply else "eklenecek"
    print(f"\nToplam {total} günce kaydı {verb}.")
    if failed:
        print(f"{failed} üyenin güncesi okunamadı; aynı komut eksikleri tamamlar.")
    if not apply:
        print("Uygulamak için: python -m scripts.import_diary --apply")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--user", action="append", default=[], help="Yalnız bu hesap(lar)")
    parser.add_argument("--apply", action="store_true", help="Akışa gerçekten ekle")
    parser.add_argument(
        "--pause", type=float, default=3.0,
        help="Üyeler arası bekleme (saniye, varsayılan 3)",
    )
    args = parser.parse_args()

    try:
        service = _service()
    except Exception as exc:  # noqa: BLE001 - CLI anlamlı bir hata göstermeli
        print(f"Bağlanılamadı: {exc}", file=sys.stderr)
        return 1

    usernames = [u.strip().lstrip("@").lower() for u in args.user if u.strip()]
    members = _members(service, usernames)
    if not members:
        print("Eşleşen üye yok.", file=sys.stderr)
        return 1
    print(f"{len(members)} üyenin güncesi okunuyor…", flush=True)
    return asyncio.run(run(service, members, apply=args.apply, pause=args.pause))


if __name__ == "__main__":
    raise SystemExit(main())
