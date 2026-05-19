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


class SupabaseCache:
    """Drop-in replacement for Cache using Supabase PostgreSQL (JSONB)."""

    def __init__(self, client):
        self._client = client

    def get(self, namespace: str, key: str, ttl: Optional[float] = None) -> Optional[Any]:
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
            if ttl is not None:
                ts = row["created_at"].replace("Z", "+00:00")
                age = (datetime.now(timezone.utc) - datetime.fromisoformat(ts)).total_seconds()
                if age > ttl:
                    return None
            return row["value"]
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

    def clear(self, namespace: Optional[str] = None) -> None:
        try:
            q = self._client.table("tmdb_cache").delete()
            if namespace is None:
                q.neq("namespace", "").execute()
            else:
                q.eq("namespace", namespace).execute()
        except Exception:
            pass
