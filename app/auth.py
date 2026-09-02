"""Username-first account service backed by Supabase Auth.

Passwords and password hashes never enter application tables. A deterministic,
non-routable synthetic email maps each Letterboxd username to Supabase Auth while
the user-facing product remains username-only.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import re
import secrets
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Callable

from .enrich import EnrichedFilm
from .scraper import ScrapedProfile
from .taste_profile import TasteProfileSnapshot


class AuthError(Exception):
    code = "auth_failed"


class AccountExistsError(AuthError):
    code = "account_exists"


class InvalidCredentialsError(AuthError):
    code = "invalid_credentials"


class VerificationError(AuthError):
    code = "verification_failed"


class VerificationExpiredError(VerificationError):
    code = "verification_expired"


class OwnershipProofError(VerificationError):
    code = "ownership_proof_missing"


class BlendServiceError(AuthError):
    code = "blend_failed"


class TransientStorageError(AuthError):
    """A safe retryable Supabase edge failure surfaced to the HTTP layer."""

    code = "storage_temporarily_unavailable"


@dataclass
class Account:
    id: int
    auth_user_id: str
    username: str
    display_name: str = ""
    avatar_url: str = ""
    account_status: str = "active"
    profile_sync_status: str = "pending"
    onboarding_completed_at: str | None = None
    letterboxd_stats: dict = field(default_factory=dict)
    discoverable: bool = False
    letter_receiving_enabled: bool = False


@dataclass
class AuthSession:
    account: Account
    access_token: str
    refresh_token: str
    expires_in: int


@dataclass
class RegistrationChallenge:
    username: str
    verification_code: str
    expires_at: str


def validate_password(password: str, confirmation: str | None = None) -> str:
    if not isinstance(password, str) or len(password) < 10:
        raise ValueError("Parola en az 10 karakter olmalı.")
    if len(password) > 128:
        raise ValueError("Parola en fazla 128 karakter olabilir.")
    if confirmation is not None and password != confirmation:
        raise ValueError("Parolalar eşleşmiyor.")
    return password


class AuthService:
    CHALLENGE_TTL_MINUTES = 15
    MAX_CHALLENGE_ATTEMPTS = 5
    STORAGE_READ_ATTEMPTS = 3

    def __init__(
        self,
        settings,
        *,
        client_factory: Callable[[str, str], Any] | None = None,
    ):
        if not getattr(settings, "has_auth", False):
            raise RuntimeError("Auth yapılandırılmamış.")
        if client_factory is None:
            from supabase import create_client

            client_factory = create_client
        self.settings = settings
        self._client_factory = client_factory
        # Service-role requests do not carry a user's mutable auth session, so
        # the underlying HTTP connection pool can safely be reused. Auth clients
        # remain per-operation below to avoid sharing session state across users.
        self._service_client_instance = None
        self._service_client_ready = False
        self._service_client_lock = threading.Lock()
        self._activity_disabled_until = 0.0

    def _service_client(self):
        if self._service_client_ready:
            return self._service_client_instance
        with self._service_client_lock:
            if not self._service_client_ready:
                self._service_client_instance = self._client_factory(
                    self.settings.supabase_url, self.settings.supabase_key
                )
                self._service_client_ready = True
        return self._service_client_instance

    def _auth_client(self):
        return self._client_factory(
            self.settings.supabase_url, self.settings.supabase_anon_key
        )

    @staticmethod
    def _is_transient_storage_error(exc: Exception) -> bool:
        """Recognise transient Supabase edge failures, not real API 4xx errors."""
        detail = f"{type(exc).__name__} {exc}".casefold()
        return (
            "cloudflare" in detail
            or "json could not be generated" in detail
            or "json_invalid" in detail
            or "server disconnected" in detail
            or "connectionterminated" in detail
            or "remoteprotocolerror" in detail
            or "eof occurred in violation of protocol" in detail
        )

    def _retry_storage_operation(self, operation: Callable[[], Any]) -> Any:
        """Retry a caller-confirmed idempotent Supabase operation after edge errors."""
        for attempt in range(self.STORAGE_READ_ATTEMPTS):
            try:
                return operation()
            except Exception as exc:
                if not self._is_transient_storage_error(exc):
                    raise
                if attempt + 1 >= self.STORAGE_READ_ATTEMPTS:
                    raise TransientStorageError(
                        "Veri bağlantısı kısa süreli yanıt vermedi. Lütfen tekrar dene."
                    ) from exc
                # This function is called from asyncio.to_thread, so the small
                # backoff does not block FastAPI's event loop.
                time.sleep(0.25 * (attempt + 1))

    def _retry_storage_read(self, operation: Callable[[], Any]) -> Any:
        """Backward-compatible name for retrying idempotent storage reads."""
        return self._retry_storage_operation(operation)

    def check_schema(self) -> bool:
        """Verify the account schema without exposing or reading user records."""
        service = self._service_client()
        required = {
            "users": "id,auth_user_id,account_status,onboarding_completed_at,letterboxd_stats,discoverable",
            "taste_profiles": "user_id,source_fingerprint,top_directors",
            "profile_favorites": "user_id,position",
            "blend_requests": "id,status",
            "blend_results": "id,request_id",
            "user_blocks": "blocker_user_id,blocked_user_id",
            "user_reports": "id,status",
            "user_letter_keys": "user_id,public_key,key_version",
            "cinephile_letters": "id,sender_user_id,recipient_user_id,read_at",
        }
        for table, columns in required.items():
            service.table(table).select(columns).limit(0).execute()
        return True

    def check_sync_schema(self) -> bool:
        """Verify the full-history sync tables exist, without reading records.

        Kept separate from check_schema so the core profile flow still works on a
        deployment where the background-sync migration has not been run yet.
        """
        service = self._service_client()
        service.table("user_watched_films").select(
            "user_id,film_slug,details_loaded,watched_rank,poster_resolver_url"
        ).limit(0).execute()
        service.table("profile_sync_jobs").select(
            "user_id,state,phase,cursor_page,scope,sync_run_id,lease_token,lease_expires_at"
        ).limit(0).execute()
        service.table("director_images").select(
            "normalized_name,photo_url,tmdb_person_id"
        ).limit(0).execute()
        service.table("film_posters").select(
            "film_slug,poster_url,poster_resolver_url,tmdb_id,overview,director,genres,keywords,details_loaded"
        ).limit(0).execute()
        return True

    def _digest(self, value: str, *, purpose: str) -> str:
        return hmac.new(
            self.settings.auth_identity_secret.encode("utf-8"),
            f"{purpose}:{value}".encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()

    def identity_email(self, username: str) -> str:
        identity = self._digest(username, purpose="identity")[:40]
        return f"lb-{identity}@users.movieboxd.invalid"

    def challenge_hash(self, code: str) -> str:
        return self._digest(code.upper(), purpose="challenge")

    @staticmethod
    def _account(row: dict) -> Account:
        return Account(
            id=int(row["id"]),
            auth_user_id=str(row["auth_user_id"]),
            username=row["username"],
            display_name=row.get("display_name") or row["username"],
            avatar_url=row.get("avatar_url") or "",
            account_status=row.get("account_status") or "anonymous",
            profile_sync_status=row.get("profile_sync_status") or "pending",
            onboarding_completed_at=row.get("onboarding_completed_at"),
            letterboxd_stats=row.get("letterboxd_stats") or {},
            discoverable=bool(row.get("discoverable", False)),
            letter_receiving_enabled=bool(row.get("letter_receiving_enabled", False)),
        )

    @staticmethod
    def _first(result) -> dict | None:
        return (result.data or [None])[0]

    def _account_row_by_username(self, client, username: str) -> dict | None:
        def read():
            return (
                client.table("users")
                .select(
                    "id,auth_user_id,username,display_name,avatar_url,"
                    "account_status,profile_sync_status,onboarding_completed_at,letterboxd_stats,"
                    "discoverable,letter_receiving_enabled"
                )
                .eq("username", username)
                .limit(1)
                .execute()
            )
        result = self._retry_storage_read(read)
        return self._first(result)

    def _audit(self, client, user_id: int | None, event: str, ip_hash: str = "") -> None:
        try:
            client.table("auth_audit_log").insert(
                {"user_id": user_id, "event": event, "ip_hash": ip_hash or None}
            ).execute()
        except Exception:
            pass
        # Keep product-usage telemetry separate from the security audit log.
        # The table is deployed independently, so an older schema must never
        # make authentication or Blend actions fail.
        self.record_activity_event(
            user_id,
            event,
            {"source": "auth_audit"},
        )

    def record_activity_event(
        self,
        user_id: int | None,
        event_type: str,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """Best-effort, non-sensitive product activity telemetry.

        This intentionally swallows schema/network errors: analytics must not
        block a user action. Callers should only pass counts, booleans, status
        codes and other bounded metadata—never tokens, passwords or raw URLs.
        """
        if not event_type or user_id is None:
            return
        # A deployment may receive traffic before the optional analytics
        # migration has been applied. Back off after the first schema failure
        # instead of adding a failed Supabase round-trip to every request.
        if time.monotonic() < self._activity_disabled_until:
            return
        payload = metadata if isinstance(metadata, dict) else {}
        try:
            # Prevent an accidental large response/request from becoming an
            # unbounded analytics row.
            encoded = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
            if len(encoded) > 4000:
                payload = {"truncated": True}
        except (TypeError, ValueError):
            payload = {"metadata_invalid": True}
        try:
            self._service_client().table("user_activity_events").insert(
                {
                    "user_id": int(user_id) if user_id is not None else None,
                    "event_type": str(event_type)[:80],
                    "metadata": payload,
                }
            ).execute()
        except Exception:
            self._activity_disabled_until = time.monotonic() + 300.0

    def start_registration(
        self,
        username: str,
        password: str,
        profile: ScrapedProfile,
        *,
        ip_hash: str = "",
    ) -> RegistrationChallenge:
        validate_password(password)
        service = self._service_client()
        existing = self._account_row_by_username(service, username)
        if existing and existing.get("account_status") == "active":
            raise AccountExistsError("Bu Letterboxd kullanıcı adı zaten kayıtlı.")

        auth_user_id = ""
        created_new_auth_user = False
        try:
            if existing and existing.get("auth_user_id"):
                auth_user_id = str(existing["auth_user_id"])
                service.auth.admin.update_user_by_id(
                    auth_user_id,
                    {
                        "password": password,
                        "user_metadata": {"letterboxd_username": username},
                    },
                )
            else:
                created = service.auth.admin.create_user(
                    {
                        "email": self.identity_email(username),
                        "password": password,
                        "email_confirm": True,
                        "user_metadata": {"letterboxd_username": username},
                    }
                )
                auth_user_id = str(created.user.id)
                created_new_auth_user = True
            account_result = service.table("users").upsert(
                {
                    "username": username,
                    "auth_user_id": auth_user_id,
                    "display_name": profile.display_name,
                    "avatar_url": profile.avatar_url,
                    "account_status": "pending_verification",
                    "profile_sync_status": "pending",
                    "updated_at": datetime.now(timezone.utc).isoformat(),
                },
                on_conflict="username",
            ).execute()
            account_row = self._first(account_result)
            if account_row is None:
                account_row = self._account_row_by_username(service, username)
            if account_row is None:
                raise RuntimeError("Account row could not be created")

            code = f"MOVIEBOXD-{secrets.token_hex(3).upper()}"
            expires = datetime.now(timezone.utc) + timedelta(
                minutes=self.CHALLENGE_TTL_MINUTES
            )
            service.table("auth_challenges").insert(
                {
                    "user_id": account_row["id"],
                    "kind": "register",
                    "code_hash": self.challenge_hash(code),
                    "expires_at": expires.isoformat(),
                }
            ).execute()
            event = "register_restarted" if existing else "register_started"
            self._audit(service, int(account_row["id"]), event, ip_hash)
            return RegistrationChallenge(username, code, expires.isoformat())
        except AccountExistsError:
            raise
        except TransientStorageError:
            # A retryable read can also occur after creating the Supabase Auth
            # identity. Preserve the original cleanup guarantee before the
            # HTTP layer asks the user to retry.
            if auth_user_id and created_new_auth_user:
                try:
                    service.auth.admin.delete_user(auth_user_id)
                except Exception:
                    pass
            raise
        except Exception as exc:
            if auth_user_id and created_new_auth_user:
                try:
                    service.auth.admin.delete_user(auth_user_id)
                except Exception:
                    pass
            raise AuthError("Hesap oluşturulamadı.") from exc

    def _active_challenge(self, client, user_id: int, kind: str) -> dict | None:
        result = (
            client.table("auth_challenges")
            .select("id,code_hash,attempts,expires_at")
            .eq("user_id", user_id)
            .eq("kind", kind)
            .is_("consumed_at", "null")
            .order("created_at", desc=True)
            .limit(1)
            .execute()
        )
        return self._first(result)

    def verify_ownership(
        self,
        username: str,
        code: str,
        profile: ScrapedProfile,
        *,
        kind: str = "register",
        ip_hash: str = "",
    ) -> Account:
        service = self._service_client()
        row = self._account_row_by_username(service, username)
        if row is None or not row.get("auth_user_id"):
            raise VerificationError("Doğrulama başarısız.")
        challenge = self._active_challenge(service, int(row["id"]), kind)
        if challenge is None:
            raise VerificationError("Doğrulama başarısız.")
        if int(challenge.get("attempts") or 0) >= self.MAX_CHALLENGE_ATTEMPTS:
            raise VerificationError("Doğrulama deneme sınırına ulaşıldı.")
        expires = datetime.fromisoformat(challenge["expires_at"].replace("Z", "+00:00"))
        if expires <= datetime.now(timezone.utc):
            raise VerificationExpiredError("Doğrulama kodunun süresi doldu.")
        valid_code = hmac.compare_digest(
            challenge["code_hash"], self.challenge_hash(code)
        )
        proof_found = code.upper() in profile.bio.upper()
        if not (valid_code and proof_found):
            service.table("auth_challenges").update(
                {"attempts": int(challenge.get("attempts") or 0) + 1}
            ).eq("id", challenge["id"]).execute()
            raise OwnershipProofError(
                "Doğrulama kodu Letterboxd bio alanında bulunamadı."
            )

        now = datetime.now(timezone.utc).isoformat()
        service.table("auth_challenges").update({"consumed_at": now}).eq(
            "id", challenge["id"]
        ).execute()
        account_result = service.table("users").update(
            {
                "display_name": profile.display_name,
                "avatar_url": profile.avatar_url,
                "account_status": "active",
                "profile_sync_status": "pending",
                "letterboxd_stats": profile.stats or {},
                "ownership_verified_at": now,
                "updated_at": now,
            }
        ).eq("id", row["id"]).execute()
        updated = self._first(account_result) or self._account_row_by_username(
            service, username
        )
        try:
            service.table("profile_favorites").delete().eq(
                "user_id", row["id"]
            ).execute()
            favorites = [
                {
                    "user_id": int(row["id"]),
                    "position": position,
                    "slug": film.slug,
                    "title": film.title,
                    "release_year": film.year,
                    "poster_url": film.poster_url,
                }
                for position, film in enumerate(profile.favorite_films[:4], start=1)
                if film.slug and film.title
            ]
            if favorites:
                service.table("profile_favorites").insert(favorites).execute()
        except Exception:
            # Ownership is already proven. A transient snapshot write must not
            # turn a valid account into an unrecoverable half-registration;
            # the background profile rebuild will repair favorites.
            pass
        self._audit(service, int(row["id"]), f"{kind}_verified", ip_hash)
        return self._account(updated)

    def start_password_reset(
        self, username: str, *, ip_hash: str = ""
    ) -> RegistrationChallenge:
        service = self._service_client()
        row = self._account_row_by_username(service, username)
        if row is None or row.get("account_status") != "active":
            raise InvalidCredentialsError("Hesap bulunamadı.")
        code = f"MOVIEBOXD-{secrets.token_hex(3).upper()}"
        expires = datetime.now(timezone.utc) + timedelta(
            minutes=self.CHALLENGE_TTL_MINUTES
        )
        service.table("auth_challenges").insert(
            {
                "user_id": row["id"],
                "kind": "password_reset",
                "code_hash": self.challenge_hash(code),
                "expires_at": expires.isoformat(),
            }
        ).execute()
        self._audit(service, int(row["id"]), "password_reset_started", ip_hash)
        return RegistrationChallenge(username, code, expires.isoformat())

    def finish_password_reset(
        self,
        username: str,
        code: str,
        new_password: str,
        profile: ScrapedProfile,
        *,
        ip_hash: str = "",
    ) -> None:
        validate_password(new_password)
        account = self.verify_ownership(
            username, code, profile, kind="password_reset", ip_hash=ip_hash
        )
        service = self._service_client()
        service.auth.admin.update_user_by_id(
            account.auth_user_id, {"password": new_password}
        )
        self._audit(service, account.id, "password_reset_completed", ip_hash)

    def login(self, username: str, password: str, *, ip_hash: str = "") -> AuthSession:
        service = self._service_client()
        row = self._account_row_by_username(service, username)
        try:
            response = self._auth_client().auth.sign_in_with_password(
                {"email": self.identity_email(username), "password": password}
            )
            if (
                response.session is None
                or row is None
                or row.get("account_status") != "active"
            ):
                raise InvalidCredentialsError("Kullanıcı adı veya parola hatalı.")
        except InvalidCredentialsError:
            self._audit(
                service, int(row["id"]) if row else None, "login_failed", ip_hash
            )
            raise
        except Exception as exc:
            self._audit(
                service, int(row["id"]) if row else None, "login_failed", ip_hash
            )
            raise InvalidCredentialsError("Kullanıcı adı veya parola hatalı.") from exc
        self._audit(service, int(row["id"]), "login_succeeded", ip_hash)
        return AuthSession(
            account=self._account(row),
            access_token=response.session.access_token,
            refresh_token=response.session.refresh_token,
            expires_in=int(response.session.expires_in or 3600),
        )

    def current_account(self, access_token: str) -> Account:
        try:
            response = self._auth_client().auth.get_user(access_token)
            auth_user_id = str(response.user.id)
            service = self._service_client()
            result = (
                service.table("users")
                .select(
                    "id,auth_user_id,username,display_name,avatar_url,"
                    "account_status,profile_sync_status,onboarding_completed_at,letterboxd_stats,"
                    "discoverable,letter_receiving_enabled"
                )
                .eq("auth_user_id", auth_user_id)
                .eq("account_status", "active")
                .limit(1)
                .execute()
            )
            row = self._first(result)
            if row is None:
                raise InvalidCredentialsError("Oturum geçersiz.")
            return self._account(row)
        except InvalidCredentialsError:
            raise
        except Exception as exc:
            raise InvalidCredentialsError("Oturum geçersiz.") from exc

    def refresh(self, refresh_token: str) -> AuthSession:
        try:
            response = self._auth_client().auth.refresh_session(refresh_token)
            if response.session is None:
                raise InvalidCredentialsError("Oturum yenilenemedi.")
            account = self.current_account(response.session.access_token)
            return AuthSession(
                account=account,
                access_token=response.session.access_token,
                refresh_token=response.session.refresh_token,
                expires_in=int(response.session.expires_in or 3600),
            )
        except InvalidCredentialsError:
            raise
        except Exception as exc:
            raise InvalidCredentialsError("Oturum yenilenemedi.") from exc

    def revoke(self, access_token: str, refresh_token: str) -> None:
        try:
            auth = self._auth_client().auth
            auth.set_session(access_token, refresh_token)
            auth.sign_out()
        except Exception:
            pass

    def mark_sync_status(self, user_id: int, status: str) -> None:
        self._service_client().table("users").update(
            {
                "profile_sync_status": status,
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }
        ).eq("id", user_id).execute()

    def complete_onboarding(self, account: Account) -> str:
        completed_at = datetime.now(timezone.utc).isoformat()
        self._service_client().table("users").update(
            {
                "onboarding_completed_at": completed_at,
                "updated_at": completed_at,
            }
        ).eq("id", account.id).execute()
        return completed_at

    def delete_account(self, account: Account) -> None:
        """Delete the Supabase Auth identity and its cascading profile rows."""
        service = self._service_client()
        service.auth.admin.delete_user(account.auth_user_id)

    def save_profile_snapshot(
        self,
        account: Account,
        profile: ScrapedProfile,
        favorites: list[EnrichedFilm],
        taste: TasteProfileSnapshot,
    ) -> None:
        self._service_client().rpc(
            "save_profile_snapshot",
            {
                "p_user_id": account.id,
                "p_profile": {
                    "display_name": profile.display_name,
                    "avatar_url": profile.avatar_url,
                    "stats": profile.stats or {},
                },
                "p_taste": taste.to_dict(),
                "p_favorites": [
                    {
                        "position": position,
                        "slug": film.slug,
                        "title": film.title,
                        "release_year": film.year,
                        "tmdb_id": film.tmdb_id,
                        "poster_url": film.poster_url,
                    }
                    for position, film in enumerate(favorites[:4], start=1)
                ],
            },
        ).execute()

    def get_profile(self, account: Account) -> dict:
        service = self._service_client()
        taste = self._first(
            service.table("taste_profiles")
            .select("*")
            .eq("user_id", account.id)
            .limit(1)
            .execute()
        )
        favorites = (
            service.table("profile_favorites")
            .select("position,slug,title,release_year,tmdb_id,poster_url")
            .eq("user_id", account.id)
            .order("position")
            .execute()
        ).data or []
        account_data = dict(account.__dict__)
        # Keşfet alanı migration'ı henüz uygulanmadıysa mevcut profil akışını
        # bozma; kullanıcı yalnızca varsayılan olarak gizli kalır.
        try:
            visibility = self._first(
                service.table("users").select("discoverable,letter_receiving_enabled").eq("id", account.id).limit(1).execute()
            ) or {}
            account_data["discoverable"] = bool(visibility.get("discoverable", False))
            account_data["letter_receiving_enabled"] = bool(visibility.get("letter_receiving_enabled", False))
        except Exception:
            pass
        return {
            "account": account_data,
            "taste": taste,
            "favorite_films": favorites,
        }

    def set_discoverable(self, account: Account, visible: bool) -> bool:
        """Opt a user in/out of the authenticated Sinefil Sineması directory."""
        self._service_client().table("users").update(
            {
                "discoverable": bool(visible),
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }
        ).eq("id", account.id).execute()
        return bool(visible)

    # ── Sinefil Mektupları ─────────────────────────────────────────────
    # The service only stores opaque browser-encrypted packets.  In particular,
    # it never receives a letter lock password, a decrypted private key, message
    # body, or film attachment.
    def get_letter_key_material(self, account: Account) -> dict | None:
        row = self._first(
            self._service_client().table("user_letter_keys")
            .select("public_key,key_version,created_at,updated_at")
            .eq("user_id", account.id).limit(1).execute()
        )
        return row or None

    def save_letter_key_material(self, account: Account, payload: dict) -> dict:
        public_key = str(payload.get("public_key") or "")
        if not (40 <= len(public_key) <= 512):
            raise BlendServiceError("invalid_letter_key")
        now = datetime.now(timezone.utc).isoformat()
        row = self._service_client().table("user_letter_keys").upsert(
            {
                "user_id": account.id,
                "public_key": public_key,
                "key_version": 1,
                "updated_at": now,
            }, on_conflict="user_id"
        ).execute()
        return self._first(row) or {"public_key": public_key, "key_version": 1}

    def set_letter_receiving(self, account: Account, enabled: bool) -> bool:
        if enabled and not self.get_letter_key_material(account):
            raise BlendServiceError("letter_key_required")
        self._service_client().table("users").update(
            {"letter_receiving_enabled": bool(enabled), "updated_at": datetime.now(timezone.utc).isoformat()}
        ).eq("id", account.id).execute()
        return bool(enabled)

    def get_letter_recipient(self, account: Account, username: str) -> dict:
        service = self._service_client()
        recipient = self._first(
            service.table("users").select(
                "id,username,display_name,avatar_url,letter_receiving_enabled,account_status"
            ).eq("username", username).limit(1).execute()
        )
        if not recipient or recipient.get("account_status") != "active" or not recipient.get("letter_receiving_enabled"):
            raise BlendServiceError("letter_recipient_unavailable")
        blocks = service.table("user_blocks").select("blocker_user_id").or_(
            f"and(blocker_user_id.eq.{account.id},blocked_user_id.eq.{recipient['id']}),"
            f"and(blocker_user_id.eq.{recipient['id']},blocked_user_id.eq.{account.id})"
        ).limit(1).execute().data or []
        if blocks:
            raise BlendServiceError("letter_recipient_unavailable")
        key = self._first(service.table("user_letter_keys").select("public_key,key_version")
            .eq("user_id", recipient["id"]).limit(1).execute())
        if not key:
            raise BlendServiceError("letter_recipient_unavailable")
        return {"username": recipient["username"], "display_name": recipient.get("display_name") or recipient["username"],
                "avatar_url": recipient.get("avatar_url") or "", "public_key": key["public_key"],
                "key_version": int(key.get("key_version") or 1)}

    def send_letter(self, account: Account, recipient_username: str, envelope: dict) -> str:
        required = ("ciphertext", "iv", "salt", "sender_public_key", "recipient_public_key")
        if any(not isinstance(envelope.get(item), str) or not envelope[item] for item in required):
            raise BlendServiceError("invalid_letter")
        if len(envelope["ciphertext"]) > 12000 or any(len(envelope[item]) > 1024 for item in required[1:]):
            raise BlendServiceError("invalid_letter")
        try:
            result = self._service_client().rpc("send_cinephile_letter", {
                "p_sender_user_id": account.id,
                "p_recipient_username": recipient_username,
                "p_envelope": envelope,
            }).execute()
            return str(self._rpc_value(result))
        except Exception as exc:
            message = str(exc)
            known = ("letter_recipient_unavailable", "letter_send_cooldown", "letter_blocked", "invalid_letter_envelope")
            raise BlendServiceError(next((item for item in known if item in message), "letter_send_failed")) from exc

    def list_letters(self, account: Account) -> list[dict]:
        service = self._service_client()
        rows = service.table("cinephile_letters").select(
            "id,sender_user_id,recipient_user_id,sender_public_key,recipient_public_key,"
            "sender_key_version,recipient_key_version,ciphertext,iv,salt,created_at,read_at"
        ).or_(f"sender_user_id.eq.{account.id},recipient_user_id.eq.{account.id}").order("created_at", desc=True).limit(100).execute().data or []
        peers = self._accounts_by_id(service, {
            int(row["recipient_user_id"] if int(row["sender_user_id"]) == account.id else row["sender_user_id"])
            for row in rows
        })
        return [{
            "id": row["id"], "direction": "sent" if int(row["sender_user_id"]) == account.id else "received",
            "peer": peers.get(int(row["recipient_user_id"] if int(row["sender_user_id"]) == account.id else row["sender_user_id"])),
            "sender_public_key": row["sender_public_key"], "recipient_public_key": row["recipient_public_key"],
            "sender_key_version": int(row.get("sender_key_version") or 1), "recipient_key_version": int(row.get("recipient_key_version") or 1),
            "ciphertext": row["ciphertext"], "iv": row["iv"], "salt": row["salt"], "created_at": row["created_at"], "read_at": row.get("read_at"),
        } for row in rows]

    def mark_letter_read(self, account: Account, letter_id: str) -> bool:
        result = self._service_client().table("cinephile_letters").update(
            {"read_at": datetime.now(timezone.utc).isoformat()}
        ).eq("id", letter_id).eq("recipient_user_id", account.id).is_("read_at", "null").execute()
        return bool(result.data)

    def count_unread_letters(self, account: Account) -> int:
        rows = self._service_client().table("cinephile_letters").select("id").eq(
            "recipient_user_id", account.id).is_("read_at", "null").execute().data or []
        return len(rows)

    def letter_send_status(self, account: Account) -> dict:
        """Expose only the sender's own 24h cooldown, never letter content."""
        row = self._first(
            self._service_client().table("cinephile_letters").select("created_at")
            .eq("sender_user_id", account.id).order("created_at", desc=True).limit(1).execute()
        )
        if not row or not row.get("created_at"):
            return {"can_send": True, "seconds_remaining": 0, "next_send_at": None}
        try:
            sent_at = datetime.fromisoformat(str(row["created_at"]).replace("Z", "+00:00"))
            next_at = sent_at + timedelta(hours=24)
            remaining = max(0, int((next_at - datetime.now(timezone.utc)).total_seconds()))
            return {"can_send": remaining == 0, "seconds_remaining": remaining, "next_send_at": next_at.isoformat()}
        except ValueError:
            return {"can_send": False, "seconds_remaining": 60, "next_send_at": None}

    @staticmethod
    def _safe_slug_set(values) -> set[str]:
        return {
            str(value).strip().lower()
            for value in (values or [])
            if isinstance(value, str) and value.strip()
        }

    @staticmethod
    def _overlap(left, right) -> set[str]:
        return {
            str(value).strip().casefold()
            for value in (left or [])
            if isinstance(value, str) and value.strip()
        } & {
            str(value).strip().casefold()
            for value in (right or [])
            if isinstance(value, str) and value.strip()
        }

    def list_sinefil_cards(self, account: Account, query: str = "") -> list[dict]:
        """Build safe, lightweight discovery cards without scraping or LLM calls."""
        service = self._service_client()
        viewer = self.get_profile(account)
        viewer_favorites = viewer.get("favorite_films") or []
        viewer_fav_titles = {
            str(row.get("slug") or "").lower(): str(row.get("title") or "")
            for row in viewer_favorites if row.get("slug")
        }
        viewer_fav = set(viewer_fav_titles)
        viewer_top = self._safe_slug_set(self.get_curated_top_film_slugs(account))
        viewer_taste = viewer.get("taste") or {}

        candidates_query = (
            service.table("users")
            .select("id,username,display_name,avatar_url,top_films,letter_receiving_enabled")
            .eq("account_status", "active")
            .eq("profile_sync_status", "ready")
            .eq("discoverable", True)
            .neq("id", account.id)
            .order("username")
            .limit(250)
        )
        if query:
            candidates_query = candidates_query.ilike("username", f"%{query}%")
        candidates = candidates_query.execute().data or []
        if not candidates:
            return []

        block_rows = (
            service.table("user_blocks")
            .select("blocker_user_id,blocked_user_id")
            .or_(f"blocker_user_id.eq.{account.id},blocked_user_id.eq.{account.id}")
            .execute()
        ).data or []
        blocked = {
            int(row["blocked_user_id"])
            if int(row["blocker_user_id"]) == account.id
            else int(row["blocker_user_id"])
            for row in block_rows
        }
        candidates = [row for row in candidates if int(row["id"]) not in blocked]
        ids = [int(row["id"]) for row in candidates]
        if not ids:
            return []
        favorites_rows = (
            service.table("profile_favorites")
            .select("user_id,position,slug,title,release_year,poster_url")
            .in_("user_id", ids)
            .order("position")
            .execute()
        ).data or []
        taste_rows = (
            service.table("taste_profiles")
            .select("user_id,top_directors,top_genres,top_keywords")
            .in_("user_id", ids)
            .execute()
        ).data or []
        favorites_by_user: dict[int, list[dict]] = {}
        for row in favorites_rows:
            favorites_by_user.setdefault(int(row["user_id"]), []).append(row)
        taste_by_user = {int(row["user_id"]): row for row in taste_rows}

        cards: list[dict] = []
        for candidate in candidates:
            user_id = int(candidate["id"])
            favorites = favorites_by_user.get(user_id, [])[:4]
            candidate_fav_titles = {
                str(row.get("slug") or "").lower(): str(row.get("title") or "")
                for row in favorites if row.get("slug")
            }
            candidate_fav = set(candidate_fav_titles)
            candidate_top = self._safe_slug_set(candidate.get("top_films"))
            same_fav4 = viewer_fav & candidate_fav
            viewer_fav_to_top10 = viewer_fav & candidate_top
            viewer_top_to_fav4 = viewer_top & candidate_fav
            shared_top10 = viewer_top & candidate_top
            taste = taste_by_user.get(user_id, {})
            directors = self._overlap(viewer_taste.get("top_directors"), taste.get("top_directors"))
            genres = self._overlap(viewer_taste.get("top_genres"), taste.get("top_genres"))
            keywords = self._overlap(viewer_taste.get("top_keywords"), taste.get("top_keywords"))
            score = min(100, (
                len(same_fav4) * 42
                + (len(viewer_fav_to_top10) + len(viewer_top_to_fav4)) * 22
                + len(shared_top10) * 7
                + len(directors) * 6 + len(genres) * 4 + len(keywords) * 2
            ))
            shared_titles: list[str] = []
            for slug in list(same_fav4) + list(viewer_fav_to_top10):
                title = viewer_fav_titles.get(slug)
                if title and title not in shared_titles:
                    shared_titles.append(title)
            for slug in list(viewer_top_to_fav4):
                title = candidate_fav_titles.get(slug)
                if title and title not in shared_titles:
                    shared_titles.append(title)
            has_favorite_match = bool(same_fav4 or viewer_fav_to_top10 or viewer_top_to_fav4)
            cards.append({
                "username": candidate["username"],
                "display_name": candidate.get("display_name") or candidate["username"],
                "avatar_url": candidate.get("avatar_url") or "",
                "favorites": [
                    {
                        "slug": row.get("slug") or "",
                        "title": row.get("title") or "",
                        "release_year": row.get("release_year"),
                        "poster_url": row.get("poster_url") or "",
                    }
                    for row in favorites
                ],
                "match_score": score,
                "has_favorite_match": has_favorite_match,
                "shared_titles": shared_titles[:3],
                "match_note": (
                    "Film zevkiniz benziyor"
                    if has_favorite_match
                    else ("Benzer yönetmenlere dönüyorsunuz" if directors else "Zevk haritalarınız yakın")
                ),
                "letters_open": bool(candidate.get("letter_receiving_enabled", False)),
            })
        return sorted(cards, key=lambda card: (-int(card["has_favorite_match"]), -card["match_score"], card["username"]))

    def sinefil_personality(self, account: Account, username: str) -> str:
        """Return only the opted-in profile's saved Fav-4 read."""
        cards = self.list_sinefil_cards(account, query=username)
        if not any(card["username"] == username for card in cards):
            raise BlendServiceError("recipient_not_found")
        row = self._first(
            self._service_client().table("users").select("id").eq("username", username).limit(1).execute()
        ) or {}
        taste = self._first(
            self._service_client().table("taste_profiles").select("personality").eq("user_id", row.get("id")).limit(1).execute()
        ) or {}
        return str(taste.get("personality") or "")

    # ── "Top 10 films" — user-curated, falls back to highest rated ────────
    _WATCHED_PICK_COLS = (
        "film_slug,title,release_year,director,user_rating,poster_url,tmdb_id"
    )
    _SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,159}$")

    @staticmethod
    def _film_row(row: dict) -> dict:
        return {
            "slug": row.get("film_slug") or "",
            "title": row.get("title") or "",
            "director": row.get("director") or "",
            "year": row.get("release_year"),
            "user_rating": row.get("user_rating"),
            "poster_url": row.get("poster_url") or "",
            "tmdb_id": row.get("tmdb_id"),
        }

    def watched_films_by_slugs(self, user_id: int, slugs: list[str]) -> dict[str, dict]:
        if not slugs:
            return {}
        rows = (
            self._service_client()
            .table("user_watched_films")
            .select(self._WATCHED_PICK_COLS)
            .eq("user_id", user_id)
            .in_("film_slug", list(slugs)[:50])
            .execute()
        ).data or []
        return {r["film_slug"]: self._film_row(r) for r in rows if r.get("film_slug")}

    def watched_film_by_slug(self, user_id: int, slug: str) -> dict | None:
        def read():
            return (
                self._service_client()
                .table("user_watched_films")
                .select(self._WATCHED_PICK_COLS)
                .eq("user_id", user_id)
                .eq("film_slug", slug)
                .limit(1)
                .execute()
            )

        rows = self._retry_storage_read(read).data or []
        return self._film_row(rows[0]) if rows else None

    def _default_top_films(self, user_id: int, limit: int = 10) -> list[dict]:
        rows = (
            self._service_client()
            .table("user_watched_films")
            .select(self._WATCHED_PICK_COLS)
            .eq("user_id", user_id)
            .eq("is_active", True)
            .not_.is_("user_rating", "null")
            .order("user_rating", desc=True)
            .order("watched_rank")
            .limit(limit)
            .execute()
        ).data or []
        return [self._film_row(r) for r in rows]

    def resolve_top_films(self, account: Account) -> list[dict]:
        service = self._service_client()
        slugs: list[str] = []
        try:  # the top_films column may predate the migration
            row = self._first(
                service.table("users").select("top_films").eq("id", account.id).execute()
            ) or {}
            slugs = [
                s for s in (row.get("top_films") or [])
                if isinstance(s, str) and self._SLUG_RE.match(s)
            ][:10]
        except Exception:
            slugs = []
        try:
            if not slugs:
                return self._default_top_films(account.id)
            picked = (
                service.table("user_watched_films")
                .select(self._WATCHED_PICK_COLS)
                .eq("user_id", account.id)
                .in_("film_slug", slugs)
                .execute()
            ).data or []
            by_slug = {r["film_slug"]: self._film_row(r) for r in picked}
            return [by_slug[s] for s in slugs if s in by_slug]
        except Exception:
            return []

    def get_curated_top_film_slugs(self, account: Account) -> list[str]:
        """Return only the user's explicit Top 10 choices, without a fallback."""
        try:
            row = self._first(
                self._service_client()
                .table("users")
                .select("top_films")
                .eq("id", account.id)
                .execute()
            ) or {}
        except Exception:
            return []
        return [
            slug
            for slug in (row.get("top_films") or [])
            if isinstance(slug, str) and self._SLUG_RE.match(slug)
        ][:10]

    def list_recent_watched(self, user_id: int, limit: int = 10) -> list[dict]:
        rows = (
            self._service_client()
            .table("user_watched_films")
            .select(self._WATCHED_PICK_COLS)
            .eq("user_id", user_id)
            .eq("is_active", True)
            .order("watched_rank", nullsfirst=False)
            .limit(limit)
            .execute()
        ).data or []
        return [self._film_row(r) for r in rows]

    def list_watched_for_picker(
        self, user_id: int, query: str = "", limit: int = 60
    ) -> list[dict]:
        builder = (
            self._service_client()
            .table("user_watched_films")
            .select(self._WATCHED_PICK_COLS)
            .eq("user_id", user_id)
            .eq("is_active", True)
        )
        if query:
            builder = builder.ilike("title", f"%{query}%")
        rows = (
            builder.order("user_rating", desc=True, nullsfirst=False)
            .order("watched_rank")
            .limit(limit)
            .execute()
        ).data or []
        return [self._film_row(r) for r in rows]

    def set_top_films(self, account: Account, slugs: list) -> list[dict]:
        clean: list[str] = []
        for raw in slugs or []:
            s = str(raw or "").strip().lower()
            if s and s not in clean and self._SLUG_RE.match(s):
                clean.append(s)
            if len(clean) >= 10:
                break
        if clean:
            watched = (
                self._service_client()
                .table("user_watched_films")
                .select("film_slug")
                .eq("user_id", account.id)
                .in_("film_slug", clean)
                .execute()
            ).data or []
            valid = {r["film_slug"] for r in watched}
            clean = [s for s in clean if s in valid]
        self._service_client().table("users").update(
            {"top_films": clean, "updated_at": datetime.now(timezone.utc).isoformat()}
        ).eq("id", account.id).execute()
        return self.resolve_top_films(account)

    # ── Full-history background sync ──────────────────────────────────────
    def get_sync_job(self, user_id: int) -> dict | None:
        def read():
            return (
                self._service_client()
                .table("profile_sync_jobs")
                .select("*")
                .eq("user_id", user_id)
                .limit(1)
                .execute()
            )

        return self._first(self._retry_storage_read(read))

    def upsert_sync_job(self, user_id: int, **fields) -> dict:
        payload = {
            "user_id": user_id,
            "updated_at": datetime.now(timezone.utc).isoformat(),
            **fields,
        }
        def write():
            return (
                self._service_client()
                .table("profile_sync_jobs")
                .upsert(payload, on_conflict="user_id")
                .execute()
            )

        row = self._first(self._retry_storage_operation(write))
        return row or payload

    def touch_sync_job(
        self, user_id: int, *, owned_by: str | None = None, **fields
    ) -> bool:
        now = datetime.now(timezone.utc).isoformat()
        def write():
            query = self._service_client().table("profile_sync_jobs").update(
                {"heartbeat_at": now, "updated_at": now, **fields}
            ).eq("user_id", user_id)
            if owned_by:
                query = query.eq("lease_token", owned_by)
            return query.execute()

        result = self._retry_storage_operation(write)
        return bool(result.data)

    def claim_sync_job(
        self, user_id: int, lease_token: str, lease_seconds: int = 360
    ) -> bool:
        result = self._service_client().rpc(
            "claim_profile_sync_job",
            {
                "p_user_id": user_id,
                "p_lease_token": lease_token,
                "p_lease_seconds": lease_seconds,
            },
        ).execute()
        return bool(self._rpc_value(result))

    def finalize_sync_run(self, user_id: int, sync_run_id: str) -> int:
        result = self._service_client().rpc(
            "finalize_profile_sync_run",
            {"p_user_id": user_id, "p_sync_run_id": sync_run_id},
        ).execute()
        try:
            return int(self._rpc_value(result) or 0)
        except (TypeError, ValueError):
            return 0

    def save_watched_films(self, user_id: int, films: list[dict]) -> int:
        """Atomic batch upsert into user_watched_films via the SQL guard."""
        if not films:
            return 0
        result = self._retry_storage_operation(
            lambda: self._service_client().rpc(
                "upsert_watched_films",
                {"p_user_id": user_id, "p_films": films},
            ).execute()
        )
        # Every public film observation feeds the account-independent catalog.
        # Keeping promotion at this boundary means account deletion can remove
        # personal ratings/history without discarding reusable film metadata.
        self.save_film_posters(
            [
                {
                    "slug": row.get("slug") or row.get("film_slug"),
                    "poster_url": row.get("poster_url"),
                    "poster_resolver_url": row.get("poster_resolver_url"),
                    "tmdb_id": row.get("tmdb_id"),
                    "title": row.get("title") or "",
                    "release_year": row.get("release_year") or row.get("year"),
                    "overview": row.get("overview") or "",
                    "director": row.get("director") or "",
                    "genres": row.get("genres") or [],
                    "keywords": row.get("keywords") or [],
                    "vote_average": row.get("vote_average") or 0,
                    "matched": bool(row.get("tmdb_id") or row.get("matched")),
                    "details_loaded": bool(row.get("details_loaded")),
                }
                for row in films
                if row.get("slug") or row.get("film_slug")
            ]
        )
        try:
            return int(result.data)
        except (TypeError, ValueError):
            return 0

    def _paginate(self, table: str, columns: str, user_id: int, *, order: str | None = None):
        service = self._service_client()
        page = 1000
        offset = 0
        out: list[dict] = []
        while True:
            query = service.table(table).select(columns).eq("user_id", user_id)
            if order:
                query = query.order(order)
            rows = (query.range(offset, offset + page - 1).execute()).data or []
            out.extend(rows)
            if len(rows) < page:
                return out
            offset += page

    def get_watched_films(self, user_id: int) -> list[dict]:
        service = self._service_client()
        page = 1000
        offset = 0
        out: list[dict] = []
        while True:
            def read():
                return (
                    service.table("user_watched_films")
                    .select(
                        "film_slug,title,release_year,tmdb_id,director,genres,keywords,"
                        "user_rating,poster_url,poster_resolver_url,watched_rank,details_loaded"
                    )
                    .eq("user_id", user_id)
                    .eq("is_active", True)
                    .order("watched_rank")
                    .range(offset, offset + page - 1)
                    .execute()
                )

            rows = self._retry_storage_read(read).data or []
            out.extend(rows)
            if len(rows) < page:
                return out
            offset += page

    def get_watched_slugs(self, user_id: int) -> set[str]:
        service = self._service_client()
        page = 1000
        offset = 0
        slugs: set[str] = set()
        while True:
            def read():
                return (
                    service.table("user_watched_films")
                    .select("film_slug")
                    .eq("user_id", user_id)
                    .eq("is_active", True)
                    .range(offset, offset + page - 1)
                    .execute()
                )

            rows = self._retry_storage_read(read).data or []
            slugs.update(row["film_slug"] for row in rows if row.get("film_slug"))
            if len(rows) < page:
                return slugs
            offset += page

    def count_watched_films(self, user_id: int) -> int:
        return len(self.get_watched_slugs(user_id))

    # ── Shared account-independent film catalog ─────────────────────────
    def save_film_posters(self, films: list[dict]) -> int:
        rows = [f for f in films if f.get("slug")]
        if not rows:
            return 0
        try:
            result = self._retry_storage_operation(
                lambda: self._service_client().rpc(
                    "upsert_film_posters", {"p_films": rows}
                ).execute()
            )
            return int(result.data)
        except Exception:
            return 0

    def get_film_posters(self, slugs) -> dict[str, str]:
        wanted = [s for s in dict.fromkeys(slugs) if s]
        if not wanted:
            return {}
        service = self._service_client()
        out: dict[str, str] = {}
        for i in range(0, len(wanted), 200):
            chunk = wanted[i : i + 200]
            rows = (
                service.table("film_posters")
                .select("film_slug,poster_url")
                .in_("film_slug", chunk)
                .execute()
            ).data or []
            for row in rows:
                if row.get("poster_url"):
                    out[row["film_slug"]] = row["poster_url"]
        return out

    def get_film_assets(self, slugs) -> dict[str, dict]:
        wanted = [s for s in dict.fromkeys(slugs) if s]
        if not wanted:
            return {}
        service = self._service_client()
        out: dict[str, dict] = {}
        for i in range(0, len(wanted), 200):
            rows = (
                service.table("film_posters")
                .select(
                    "film_slug,poster_url,poster_resolver_url,tmdb_id,title,release_year,overview,"
                    "director,genres,keywords,vote_average,matched,details_loaded"
                )
                .in_("film_slug", wanted[i : i + 200])
                .execute()
            ).data or []
            out.update({row["film_slug"]: row for row in rows if row.get("film_slug")})
        return out

    def get_film_posters_by_tmdb_ids(self, tmdb_ids) -> dict[int, str]:
        wanted = [int(value) for value in dict.fromkeys(tmdb_ids) if value]
        if not wanted:
            return {}
        out: dict[int, str] = {}
        service = self._service_client()
        for i in range(0, len(wanted), 200):
            rows = (
                service.table("film_posters")
                .select("tmdb_id,poster_url")
                .in_("tmdb_id", wanted[i : i + 200])
                .execute()
            ).data or []
            for row in rows:
                if row.get("tmdb_id") and row.get("poster_url"):
                    out[int(row["tmdb_id"])] = row["poster_url"]
        return out

    def get_director_images(self, names) -> dict[str, str]:
        assets = self.get_director_assets(names)
        return {
            name: row["photo_url"]
            for name, row in assets.items()
            if row.get("photo_url")
        }

    def get_director_assets(self, names) -> dict[str, dict]:
        requested = [str(name).strip() for name in dict.fromkeys(names) if str(name).strip()]
        normalized = [name.lower() for name in requested]
        if not normalized:
            return {}
        rows = (
            self._service_client()
            .table("director_images")
            .select("normalized_name,display_name,photo_url,tmdb_person_id")
            .in_("normalized_name", normalized)
            .execute()
        ).data or []
        by_normalized = {
            row["normalized_name"]: row
            for row in rows
            if row.get("normalized_name")
        }
        return {
            name: by_normalized[name.lower()]
            for name in requested
            if name.lower() in by_normalized
        }

    def save_director_images(self, directors: list[dict]) -> int:
        rows = [
            row for row in directors
            if row.get("name") and row.get("photo_url")
        ]
        if not rows:
            return 0
        result = self._service_client().rpc(
            "upsert_director_images", {"p_directors": rows}
        ).execute()
        try:
            return int(self._rpc_value(result) or 0)
        except (TypeError, ValueError):
            return 0

    def list_director_films(
        self, user_id: int, director: str, *, limit: int = 60, offset: int = 0
    ) -> list[dict]:
        return (
            self._service_client()
            .table("user_watched_films")
            .select("film_slug,title,release_year,poster_url,user_rating,watched_rank")
            .eq("user_id", user_id)
            .eq("is_active", True)
            .eq("director", director)
            .order("user_rating", desc=True, nullsfirst=False)
            .order("watched_rank")
            .range(offset, offset + limit - 1)
            .execute()
        ).data or []

    def search_accounts(self, account: Account, query: str, limit: int = 8) -> list[dict]:
        service = self._service_client()
        result = (
            service
            .table("users")
            .select("id,username,display_name,avatar_url")
            .eq("account_status", "active")
            .neq("id", account.id)
            .ilike("username", f"%{query}%")
            .order("username")
            .limit(24)
            .execute()
        )
        blocks = (
            service.table("user_blocks")
            .select("blocker_user_id,blocked_user_id")
            .or_(f"blocker_user_id.eq.{account.id},blocked_user_id.eq.{account.id}")
            .execute()
        ).data or []
        blocked_ids = {
            int(row["blocked_user_id"])
            if int(row["blocker_user_id"]) == account.id
            else int(row["blocker_user_id"])
            for row in blocks
        }
        safe_limit = max(1, min(limit, 12))
        return [
            {key: value for key, value in row.items() if key != "id"}
            for row in (result.data or [])
            if int(row["id"]) not in blocked_ids
        ][:safe_limit]

    @staticmethod
    def _rpc_value(result):
        data = result.data
        if isinstance(data, list) and len(data) == 1:
            return data[0]
        return data

    def create_blend_request(
        self, account: Account, recipient_username: str, *, ip_hash: str = ""
    ) -> str:
        service = self._service_client()
        try:
            result = service.rpc(
                "create_blend_request",
                {
                    "p_requester_user_id": account.id,
                    "p_recipient_username": recipient_username,
                },
            ).execute()
            request_id = str(self._rpc_value(result))
            self._audit(service, account.id, "blend_request_created", ip_hash)
            return request_id
        except Exception as exc:
            message = str(exc)
            known = (
                "recipient_not_found",
                "self_request",
                "blend_request_exists",
                "blend_already_accepted",
                "pending_quota_reached",
                "blend_user_blocked",
            )
            code = next((item for item in known if item in message), "blend_request_failed")
            raise BlendServiceError(code) from exc

    def find_blend_relation(
        self, account: Account, recipient_username: str
    ) -> dict | None:
        """Find an accepted or still-live pending Blend for one unordered pair."""
        service = self._service_client()
        peer = self._first(
            service.table("users")
            .select("id,username")
            .eq("username", recipient_username.strip().lstrip("@").lower())
            .eq("account_status", "active")
            .limit(1)
            .execute()
        )
        if not peer:
            return None
        peer_id = int(peer["id"])
        rows = (
            service.table("blend_requests")
            .select(
                "id,requester_user_id,recipient_user_id,status,created_at,expires_at"
            )
            .or_(
                f"and(requester_user_id.eq.{account.id},recipient_user_id.eq.{peer_id}),"
                f"and(requester_user_id.eq.{peer_id},recipient_user_id.eq.{account.id})"
            )
            .in_("status", ["accepted", "pending"])
            .order("created_at", desc=True)
            .limit(20)
            .execute()
        ).data or []
        now = datetime.now(timezone.utc)
        accepted = next((row for row in rows if row.get("status") == "accepted"), None)
        if accepted:
            return {
                "request_id": str(accepted["id"]),
                "status": "accepted",
                "direction": (
                    "incoming"
                    if int(accepted["recipient_user_id"]) == account.id
                    else "outgoing"
                ),
            }
        for row in rows:
            if row.get("status") != "pending":
                continue
            expires = row.get("expires_at")
            if isinstance(expires, str):
                try:
                    expires = datetime.fromisoformat(expires.replace("Z", "+00:00"))
                except ValueError:
                    expires = None
            if isinstance(expires, datetime) and expires.tzinfo is None:
                expires = expires.replace(tzinfo=timezone.utc)
            if expires and expires <= now:
                continue
            return {
                "request_id": str(row["id"]),
                "status": "pending",
                "direction": (
                    "incoming"
                    if int(row["recipient_user_id"]) == account.id
                    else "outgoing"
                ),
            }
        return None

    def decide_blend_request(
        self,
        account: Account,
        request_id: str,
        decision: str,
        *,
        ip_hash: str = "",
    ) -> dict:
        service = self._service_client()
        try:
            result = service.rpc(
                "decide_blend_request",
                {
                    "p_request_id": request_id,
                    "p_recipient_user_id": account.id,
                    "p_decision": decision,
                },
            ).execute()
            row = self._rpc_value(result) or {}
            self._audit(service, account.id, f"blend_request_{decision}", ip_hash)
            return row
        except Exception as exc:
            message = str(exc)
            known = (
                "invalid_decision",
                "request_not_found",
                "forbidden",
                "request_already_decided",
            )
            code = next((item for item in known if item in message), "blend_decision_failed")
            raise BlendServiceError(code) from exc

    def cancel_blend_request(self, account: Account, request_id: str) -> None:
        try:
            self._service_client().rpc(
                "cancel_blend_request",
                {
                    "p_request_id": request_id,
                    "p_requester_user_id": account.id,
                },
            ).execute()
            self._audit(self._service_client(), account.id, "blend_request_cancelled")
        except Exception as exc:
            raise BlendServiceError("request_not_cancellable") from exc

    def _accounts_by_id(self, service, user_ids: set[int]) -> dict[int, dict]:
        if not user_ids:
            return {}
        users = (
            service.table("users")
            .select("id,username,display_name,avatar_url")
            .in_("id", list(user_ids))
            .execute()
        ).data or []
        return {
            int(row["id"]): {
                "username": row["username"],
                "display_name": row.get("display_name") or row["username"],
                "avatar_url": row.get("avatar_url") or "",
            }
            for row in users
        }

    def list_blends(self, account: Account) -> dict:
        service = self._service_client()
        now = datetime.now(timezone.utc).isoformat()
        try:
            (
                service.table("blend_requests")
                .update({"status": "expired", "decided_at": now})
                .eq("status", "pending")
                .lt("expires_at", now)
                .execute()
            )
        except Exception:
            pass
        requests = (
            service.table("blend_requests")
            .select(
                "id,requester_user_id,recipient_user_id,status,created_at,"
                "decided_at,expires_at"
            )
            .or_(
                f"requester_user_id.eq.{account.id},recipient_user_id.eq.{account.id}"
            )
            .order("created_at", desc=True)
            .limit(100)
            .execute()
        ).data or []
        blocked_rows = (
            service.table("user_blocks")
            .select("blocked_user_id,created_at")
            .eq("blocker_user_id", account.id)
            .order("created_at", desc=True)
            .execute()
        ).data or []
        user_ids = {
            int(row["requester_user_id"])
            if int(row["requester_user_id"]) != account.id
            else int(row["recipient_user_id"])
            for row in requests
        }
        user_ids.update(int(row["blocked_user_id"]) for row in blocked_rows)
        accounts = self._accounts_by_id(service, user_ids)
        request_ids = [row["id"] for row in requests]
        results = []
        if request_ids:
            results = (
                service.table("blend_results")
                .select(
                    "id,request_id,score,confidence,algorithm_version,created_at"
                )
                .in_("request_id", request_ids)
                .execute()
            ).data or []
        result_by_request = {row["request_id"]: row for row in results}

        incoming, outgoing, history = [], [], []
        for row in requests:
            is_incoming = int(row["recipient_user_id"]) == account.id
            peer_id = int(
                row["requester_user_id"] if is_incoming else row["recipient_user_id"]
            )
            item = {
                **row,
                "direction": "incoming" if is_incoming else "outgoing",
                "peer": accounts.get(peer_id),
                "blend_result": result_by_request.get(row["id"]),
            }
            if row["status"] == "pending":
                (incoming if is_incoming else outgoing).append(item)
            else:
                history.append(item)
        blocked = [
            {
                "created_at": row["created_at"],
                "user": accounts.get(int(row["blocked_user_id"])),
            }
            for row in blocked_rows
        ]
        return {
            "incoming": incoming,
            "outgoing": outgoing,
            "history": history,
            "blocked": blocked,
        }

    def count_pending_blend_requests(self, account: Account) -> int:
        """Lightweight inbox badge count; no peer/result payload is loaded."""
        rows = (
            self._service_client()
            .table("blend_requests")
            .select("id")
            .eq("recipient_user_id", account.id)
            .eq("status", "pending")
            .execute()
        ).data or []
        return len(rows)

    def get_blend_participants(
        self, account: Account, request_id: str
    ) -> tuple[dict, Account, Account]:
        service = self._service_client()
        request = self._first(
            service.table("blend_requests")
            .select("id,requester_user_id,recipient_user_id,status")
            .eq("id", request_id)
            .limit(1)
            .execute()
        )
        if request is None or request.get("status") != "accepted":
            raise BlendServiceError("accepted_request_not_found")
        if account.id not in (
            int(request["requester_user_id"]),
            int(request["recipient_user_id"]),
        ):
            raise BlendServiceError("forbidden")
        rows = (
            service.table("users")
            .select(
                "id,auth_user_id,username,display_name,avatar_url,"
                "account_status,profile_sync_status,onboarding_completed_at,letterboxd_stats"
            )
            .in_(
                "id",
                [request["requester_user_id"], request["recipient_user_id"]],
            )
            .execute()
        ).data or []
        by_id = {int(row["id"]): self._account(row) for row in rows}
        try:
            requester = by_id[int(request["requester_user_id"])]
            recipient = by_id[int(request["recipient_user_id"])]
        except KeyError as exc:
            raise BlendServiceError("participant_not_found") from exc
        return request, requester, recipient

    def get_blend_result(self, request_id: str) -> dict | None:
        return self._first(
            self._service_client()
            .table("blend_results")
            .select(
                "id,request_id,score,confidence,result,algorithm_version,created_at"
            )
            .eq("request_id", request_id)
            .limit(1)
            .execute()
        )

    def save_blend_result(
        self,
        account: Account,
        request_id: str,
        result: dict,
        *,
        algorithm_version: str,
    ) -> str:
        try:
            response = self._service_client().rpc(
                "save_blend_result",
                {
                    "p_request_id": request_id,
                    "p_actor_user_id": account.id,
                    "p_score": result["score"],
                    "p_confidence": result["confidence"],
                    "p_result": result,
                    "p_algorithm_version": algorithm_version,
                },
            ).execute()
            return str(self._rpc_value(response))
        except Exception as exc:
            raise BlendServiceError("blend_result_save_failed") from exc

    def delete_blend(self, account: Account, request_id: str) -> None:
        """Delete the shared request; its result cascades for both participants."""
        service = self._service_client()
        # Reuse the accepted-participant guard before the service-role delete.
        self.get_blend_participants(account, request_id)
        try:
            service.table("blend_requests").delete().eq("id", request_id).execute()
        except Exception as exc:
            raise BlendServiceError("blend_delete_failed") from exc
        try:
            self._audit(service, account.id, "blend_deleted", "")
        except Exception:
            pass

    def block_user(self, account: Account, username: str) -> None:
        try:
            self._service_client().rpc(
                "block_user",
                {
                    "p_blocker_user_id": account.id,
                    "p_blocked_username": username,
                },
            ).execute()
            self._audit(self._service_client(), account.id, "user_blocked")
        except Exception as exc:
            message = str(exc)
            code = next(
                (item for item in ("user_not_found", "self_block") if item in message),
                "block_failed",
            )
            raise BlendServiceError(code) from exc

    def unblock_user(self, account: Account, username: str) -> None:
        try:
            self._service_client().rpc(
                "unblock_user",
                {
                    "p_blocker_user_id": account.id,
                    "p_blocked_username": username,
                },
            ).execute()
            self._audit(self._service_client(), account.id, "user_unblocked")
        except Exception as exc:
            raise BlendServiceError("unblock_failed") from exc

    def report_user(
        self, account: Account, username: str, category: str, detail: str
    ) -> str:
        try:
            response = self._service_client().rpc(
                "report_user",
                {
                    "p_reporter_user_id": account.id,
                    "p_reported_username": username,
                    "p_category": category,
                    "p_detail": detail[:500],
                },
            ).execute()
            self._audit(self._service_client(), account.id, "user_reported")
            return str(self._rpc_value(response))
        except Exception as exc:
            message = str(exc)
            known = (
                "invalid_report_category",
                "user_not_found",
                "self_report",
                "report_quota_reached",
            )
            code = next((item for item in known if item in message), "report_failed")
            raise BlendServiceError(code) from exc
