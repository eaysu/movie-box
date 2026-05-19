"""A tiny SQLite-backed key-value cache.

Used to avoid hammering external APIs: TMDb lookups and scraped watchlists
are cached so repeated requests are cheap. Values are JSON-serialised.
"""

import json
import sqlite3
import time
from pathlib import Path
from typing import Any, Optional


class Cache:
    """Namespaced JSON cache with optional per-entry TTL."""

    def __init__(self, db_path: Path):
        self.db_path = db_path
        self._init_db()

    def _init_db(self) -> None:
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS cache (
                    namespace  TEXT NOT NULL,
                    key        TEXT NOT NULL,
                    value      TEXT NOT NULL,
                    created_at REAL NOT NULL,
                    PRIMARY KEY (namespace, key)
                )
                """
            )

    def get(self, namespace: str, key: str, ttl: Optional[float] = None) -> Optional[Any]:
        """Return the cached value, or None if missing / expired."""
        with sqlite3.connect(self.db_path) as conn:
            row = conn.execute(
                "SELECT value, created_at FROM cache WHERE namespace = ? AND key = ?",
                (namespace, str(key)),
            ).fetchone()
        if row is None:
            return None
        value, created_at = row
        if ttl is not None and (time.time() - created_at) > ttl:
            return None
        return json.loads(value)

    def set(self, namespace: str, key: str, value: Any) -> None:
        """Store a JSON-serialisable value."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                INSERT INTO cache (namespace, key, value, created_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT (namespace, key)
                DO UPDATE SET value = excluded.value, created_at = excluded.created_at
                """,
                (namespace, str(key), json.dumps(value), time.time()),
            )

    def clear(self, namespace: Optional[str] = None) -> None:
        """Drop one namespace, or the whole cache when namespace is None."""
        with sqlite3.connect(self.db_path) as conn:
            if namespace is None:
                conn.execute("DELETE FROM cache")
            else:
                conn.execute("DELETE FROM cache WHERE namespace = ?", (namespace,))
