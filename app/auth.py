"""Username-first account service backed by Supabase Auth.

Passwords and password hashes never enter application tables. A deterministic,
non-routable synthetic email maps each Letterboxd username to Supabase Auth while
the user-facing product remains username-only.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
from dataclasses import dataclass
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


@dataclass
class Account:
    id: int
    auth_user_id: str
    username: str
    display_name: str = ""
    avatar_url: str = ""
    account_status: str = "active"
    profile_sync_status: str = "pending"


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

    def _service_client(self):
        return self._client_factory(
            self.settings.supabase_url, self.settings.supabase_key
        )

    def _auth_client(self):
        return self._client_factory(
            self.settings.supabase_url, self.settings.supabase_anon_key
        )

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
        )

    @staticmethod
    def _first(result) -> dict | None:
        return (result.data or [None])[0]

    def _account_row_by_username(self, client, username: str) -> dict | None:
        result = (
            client.table("users")
            .select(
                "id,auth_user_id,username,display_name,avatar_url,"
                "account_status,profile_sync_status"
            )
            .eq("username", username)
            .limit(1)
            .execute()
        )
        return self._first(result)

    def _audit(self, client, user_id: int | None, event: str, ip_hash: str = "") -> None:
        try:
            client.table("auth_audit_log").insert(
                {"user_id": user_id, "event": event, "ip_hash": ip_hash or None}
            ).execute()
        except Exception:
            pass

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
                "ownership_verified_at": now,
                "updated_at": now,
            }
        ).eq("id", row["id"]).execute()
        updated = self._first(account_result) or self._account_row_by_username(
            service, username
        )
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
                    "account_status,profile_sync_status"
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
        return {
            "account": account.__dict__,
            "taste": taste,
            "favorite_films": favorites,
        }

    def search_accounts(self, account: Account, query: str, limit: int = 8) -> list[dict]:
        result = (
            self._service_client()
            .table("users")
            .select("username,display_name,avatar_url")
            .eq("account_status", "active")
            .neq("id", account.id)
            .ilike("username", f"%{query}%")
            .order("username")
            .limit(max(1, min(limit, 12)))
            .execute()
        )
        return result.data or []

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
                "pending_quota_reached",
            )
            code = next((item for item in known if item in message), "blend_request_failed")
            raise BlendServiceError(code) from exc

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
        user_ids = {
            int(row["requester_user_id"])
            if int(row["requester_user_id"]) != account.id
            else int(row["recipient_user_id"])
            for row in requests
        }
        accounts = self._accounts_by_id(service, user_ids)
        request_ids = [row["id"] for row in requests]
        results = []
        if request_ids:
            results = (
                service.table("blend_results")
                .select(
                    "id,request_id,score,confidence,result,algorithm_version,created_at"
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
        return {"incoming": incoming, "outgoing": outgoing, "history": history}

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
                "account_status,profile_sync_status"
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
