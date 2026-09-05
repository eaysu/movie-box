#!/usr/bin/env python3
"""One command to test the whole app locally, already signed in.

Registration normally needs a password and a bio code pasted into a public
Letterboxd profile. That is the right gate in production and a waste of time
when the thing being tested is onboarding itself. This script prepares the
account directly, starts the server with a loopback-only login route, and opens
the browser on it.

    python -m scripts.dev_start              # sign in, keep existing data
    python -m scripts.dev_start --fresh      # replay onboarding from scratch
    python -m scripts.dev_start --user someone_else
    python -m scripts.dev_start --no-browser --port 8010

`--fresh` wipes the profile the same way `scripts.reset_profile` does and also
clears the stored onboarding completion, which is what actually makes the slides
play again.

The account, its films and its letters live in the configured Supabase project.
There is no separate local database, so `--fresh` deletes real rows for that
username — it asks before doing so unless `--yes` is given.
"""

from __future__ import annotations

import argparse
import os
import shutil
import signal
import subprocess
import sys
import time
import urllib.error
import urllib.request
import webbrowser
from datetime import datetime, timezone

from app.config import get_settings

DEFAULT_USER = "enesaysu"


def _norm(username: str) -> str:
    return username.strip().lstrip("@").lower()


def _client():
    settings = get_settings()
    if not settings.has_supabase:
        raise RuntimeError("SUPABASE_URL / SUPABASE_KEY yapılandırılmamış (.env.local).")
    if not settings.has_auth:
        raise RuntimeError(
            "Auth yapılandırılmamış. .env.local dosyasına şunları ekle:\n"
            "    SUPABASE_ANON_KEY=<Supabase > Project Settings > API > anon key>\n"
            "    AUTH_IDENTITY_SECRET=<Render'daki AUTH_IDENTITY_SECRET ile AYNI>\n"
            "  İkincisi kritik: kullanıcı adından türetilen kimlik e-postası bu\n"
            "  sırdan üretiliyor. Farklı bir değer, var olan hesabı bulamaz."
        )
    from supabase import create_client

    return create_client(settings.supabase_url, settings.supabase_key)


def ensure_account(client, username: str, *, allow_new_identity: bool = False) -> dict:
    """Create or repair the account so a password-free login can succeed.

    Ownership verification is skipped on purpose: this is the developer's own
    machine and their own username, and the bio round-trip is exactly what makes
    repeated local testing slow.
    """
    from app.auth import AuthService

    settings = get_settings()
    service = AuthService(settings)
    email = service.identity_email(username)
    password = settings.dev_login_password
    now = datetime.now(timezone.utc).isoformat()

    row = (
        client.table("users")
        .select("id,auth_user_id,account_status,display_name")
        .eq("username", username)
        .limit(1)
        .execute()
    ).data
    account = row[0] if row else None
    auth_user_id = (account or {}).get("auth_user_id") or ""

    if auth_user_id:
        # Signing in without a password still needs a password to exist, so the
        # dev one replaces it. The account owner's old password stops working
        # until they reset it through the app.
        print("  NOT: hesabın parolası dev parolasıyla değiştiriliyor.")
        client.auth.admin.update_user_by_id(
            auth_user_id,
            {"password": password, "user_metadata": {"letterboxd_username": username}},
        )
        print(f"  kimlik güncellendi ({email})")
    elif not allow_new_identity:
        raise RuntimeError(
            f"@{username} için Supabase Auth kimliği yok. Yeni kimlik, yerel\n"
            "  AUTH_IDENTITY_SECRET'ten türetilen e-postayla açılır; bu sır\n"
            "  Render'dakinden farklıysa hesabın canlı girişi bozulur.\n"
            "  Sır aynıysa --allow-new-identity ile tekrar çalıştır."
        )
    else:
        try:
            created = client.auth.admin.create_user({
                "email": email,
                "password": password,
                "email_confirm": True,
                "user_metadata": {"letterboxd_username": username},
            })
            auth_user_id = str(created.user.id)
            print(f"  kimlik oluşturuldu ({email})")
        except Exception as exc:  # noqa: BLE001 - the identity may already exist
            raise RuntimeError(
                f"Supabase Auth kimliği oluşturulamadı: {exc}. "
                "Aynı e-posta başka bir kullanıcıda olabilir."
            ) from exc

    client.table("users").upsert(
        {
            "username": username,
            "auth_user_id": auth_user_id,
            "display_name": (account or {}).get("display_name") or username,
            "account_status": "active",
            "ownership_verified_at": now,
            "updated_at": now,
        },
        on_conflict="username",
    ).execute()
    print(f"  @{username} aktif · parola dev parolasına ayarlandı")
    return {"auth_user_id": auth_user_id}


def reset_profile(client, username: str) -> None:
    """Wipe the regenerable profile so onboarding replays."""
    from app.database import SupabaseCache
    from app.main import _delete_cached_user_data

    row = (
        client.table("users").select("id").eq("username", username).limit(1).execute()
    ).data
    if not row:
        return
    uid = row[0]["id"]
    for table in (
        "taste_profiles",
        "profile_favorites",
        "user_watched_films",
        "profile_sync_jobs",
        "bulletin_digests",
    ):
        deleted = (client.table(table).delete().eq("user_id", uid).execute()).data or []
        print(f"  {table} -{len(deleted)}")
    _delete_cached_user_data(SupabaseCache(client), username)
    client.table("users").update(
        {
            "profile_sync_status": "pending",
            "profile_synced_at": None,
            # Without this the slides stay skipped: completion is stored per
            # account, not per browser.
            "onboarding_completed_at": None,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
    ).eq("id", uid).execute()
    print("  profil sıfırlandı · onboarding tekrar oynayacak")


def wait_for_server(base_url: str, process: subprocess.Popen, timeout: float = 60.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if process.poll() is not None:
            return False
        try:
            with urllib.request.urlopen(f"{base_url}/api/health", timeout=2) as response:
                if response.status == 200:
                    return True
        except (urllib.error.URLError, OSError):
            time.sleep(0.4)
    return False


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--user", default=DEFAULT_USER, help=f"varsayılan: {DEFAULT_USER}")
    parser.add_argument(
        "--fresh", action="store_true", help="Profili sil, onboarding baştan oynasın"
    )
    parser.add_argument("--yes", action="store_true", help="--fresh için onay sorma")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--no-browser", action="store_true")
    parser.add_argument(
        "--allow-new-identity",
        action="store_true",
        help="Hesabın Supabase kimliği yoksa oluştur (AUTH_IDENTITY_SECRET aynı olmalı)",
    )
    parser.add_argument(
        "--no-server", action="store_true", help="Sunucuyu başlatma, sadece hesabı hazırla"
    )
    args = parser.parse_args()

    username = _norm(args.user)
    base_url = f"http://127.0.0.1:{args.port}"

    try:
        client = _client()
    except Exception as exc:  # noqa: BLE001 - CLI should present a useful error
        print(f"Hazırlanamadı: {exc}", file=sys.stderr)
        return 1

    print(f"@{username} hazırlanıyor…")
    if args.fresh:
        if not args.yes:
            print(
                f"\n  --fresh, @{username} hesabının profilini, izlenen filmlerini ve\n"
                "  önbelleğini Supabase'den SİLER. Mektuplar ve blendler kalır.\n"
            )
            if input("  Devam? [e/H] ").strip().lower() not in ("e", "evet", "y", "yes"):
                print("  vazgeçildi.")
                return 1
        reset_profile(client, username)

    try:
        ensure_account(client, username, allow_new_identity=args.allow_new_identity)
    except Exception as exc:  # noqa: BLE001
        print(f"Hesap hazırlanamadı: {exc}", file=sys.stderr)
        return 1

    login_url = f"{base_url}/api/dev/login?username={username}"
    if args.no_server:
        print(f"\nSunucuyu kendin başlat, sonra: {login_url}")
        print("  DEV_LOGIN_ENABLED=true uvicorn app.main:app --reload")
        return 0

    uvicorn = shutil.which("uvicorn")
    command = (
        [uvicorn, "app.main:app", "--host", "127.0.0.1", "--port", str(args.port), "--reload"]
        if uvicorn
        else [sys.executable, "-m", "uvicorn", "app.main:app",
              "--host", "127.0.0.1", "--port", str(args.port), "--reload"]
    )
    env = {
        **os.environ,
        "DEV_LOGIN_ENABLED": "true",
        # The session cookie is only sent back over plain HTTP if it is not
        # marked secure, and localhost is not HTTPS.
        "AUTH_COOKIE_SECURE": "false",
    }
    print(f"\nSunucu başlatılıyor: {base_url}")
    process = subprocess.Popen(command, env=env)
    try:
        if not wait_for_server(base_url, process):
            print("Sunucu ayağa kalkmadı; yukarıdaki hatalara bak.", file=sys.stderr)
            process.terminate()
            return 1
        print(f"Giriş yapılıyor: @{username}")
        if args.no_browser:
            print(f"  Tarayıcıda aç: {login_url}")
        else:
            webbrowser.open(login_url)
        print("\nÇıkmak için Ctrl+C.\n")
        process.wait()
    except KeyboardInterrupt:
        process.send_signal(signal.SIGINT)
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
        print("\nSunucu durduruldu.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
