"""Supabase integration — user tracking and optional cache backend.

Tables required (see supabase/schema.sql):
  - users       : letterboxd_username + timestamps
  - tmdb_cache  : namespace/key/value JSON cache (replaces SQLite in prod)
"""

from datetime import datetime, timezone
from typing import Any, Optional


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def upsert_user(client, username: str) -> None:
    """Insert or update a user row, refreshing last_seen_at."""
    try:
        client.table("users").upsert(
            {"username": username, "last_seen_at": _now_iso()},
            on_conflict="username",
        ).execute()
    except Exception:
        pass  # tracking must never fail a recommendation request


def delete_user(client, username: str) -> bool:
    """Delete the tracking row for a username; report backend success."""
    try:
        client.table("users").delete().eq("username", username).execute()
        return True
    except Exception:
        return False


class SupabaseCache:
    """Drop-in replacement for Cache using Supabase PostgreSQL (JSONB)."""

    def __init__(self, client):
        self._client = client

    def get(self, namespace: str, key: str, ttl: Optional[float] = None) -> Optional[Any]:
        entry = self.get_with_freshness(namespace, key, ttl=ttl)
        if entry is None:
            return None
        value, fresh = entry
        return value if fresh else None

    def get_with_freshness(
        self, namespace: str, key: str, ttl: Optional[float] = None
    ) -> Optional[tuple[Any, bool]]:
        """Return ``(value, fresh)`` while retaining expired rows for SWR."""
        try:
            result = (
                self._client.table("tmdb_cache")
                .select("value, created_at")
                .eq("namespace", namespace)
                .eq("key", str(key))
                .execute()
            )
            if not result.data:
                return None
            row = result.data[0]
            fresh = True
            if ttl is not None:
                ts = row["created_at"].replace("Z", "+00:00")
                age = (datetime.now(timezone.utc) - datetime.fromisoformat(ts)).total_seconds()
                fresh = age <= ttl
            return row["value"], fresh
        except Exception:
            return None

    def set(self, namespace: str, key: str, value: Any) -> None:
        try:
            self._client.table("tmdb_cache").upsert(
                {
                    "namespace": namespace,
                    "key": str(key),
                    "value": value,
                    "created_at": _now_iso(),
                },
                on_conflict="namespace,key",
            ).execute()
        except Exception:
            pass

    def get_many(
        self, namespace: str, keys: list[str], ttl: Optional[float] = None
    ) -> dict[str, Any]:
        if not keys:
            return {}
        try:
            result = (
                self._client.table("tmdb_cache")
                .select("key, value, created_at")
                .eq("namespace", namespace)
                .in_("key", [str(key) for key in keys])
                .execute()
            )
            now = datetime.now(timezone.utc)
            values = {}
            for row in result.data or []:
                if ttl is not None:
                    ts = row["created_at"].replace("Z", "+00:00")
                    age = (now - datetime.fromisoformat(ts)).total_seconds()
                    if age > ttl:
                        continue
                values[str(row["key"])] = row["value"]
            return values
        except Exception:
            return {}

    def set_many(self, namespace: str, values: dict[str, Any]) -> bool:
        if not values:
            return True
        try:
            created_at = _now_iso()
            self._client.table("tmdb_cache").upsert(
                [
                    {
                        "namespace": namespace,
                        "key": str(key),
                        "value": value,
                        "created_at": created_at,
                    }
                    for key, value in values.items()
                ],
                on_conflict="namespace,key",
            ).execute()
            return True
        except Exception:
            return False

    def touch(self, namespace: str, key: str) -> bool:
        """Refresh an existing row timestamp while keeping its value intact."""
        try:
            result = (
                self._client.table("tmdb_cache")
                .update({"created_at": _now_iso()})
                .eq("namespace", namespace)
                .eq("key", str(key))
                .execute()
            )
            return bool(result.data)
        except Exception:
            return False

    def delete(self, namespace: str, key: str) -> bool:
        try:
            self._client.table("tmdb_cache").delete().eq(
                "namespace", namespace
            ).eq("key", str(key)).execute()
            return True
        except Exception:
            return False

    def clear(self, namespace: Optional[str] = None) -> bool:
        try:
            q = self._client.table("tmdb_cache").delete()
            if namespace is None:
                q.neq("namespace", "").execute()
            else:
                q.eq("namespace", namespace).execute()
            return True
        except Exception:
            return False
