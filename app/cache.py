"""A tiny SQLite-backed key-value cache.

Used to avoid hammering external APIs: TMDb lookups and scraped watchlists
are cached so repeated requests are cheap. Values are JSON-serialised.
"""

import json
import sqlite3
import threading
import time
from contextlib import closing
from collections import defaultdict
from pathlib import Path
from typing import Any, Optional


_cache_locks_guard = threading.Lock()
_cache_write_locks: dict[str, threading.RLock] = {}


def _write_lock_for(db_path: Path) -> threading.RLock:
    """Share one write lock between Cache instances that use the same file."""
    path = str(db_path.resolve())
    with _cache_locks_guard:
        return _cache_write_locks.setdefault(path, threading.RLock())


class Cache:
    """Namespaced JSON cache with optional per-entry TTL."""

    def __init__(self, db_path: Path):
        self.db_path = db_path
        self._write_lock = _write_lock_for(db_path)
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        # Cache objects are created per request in a few call paths. A generous
        # busy timeout plus WAL lets their short reads proceed while a batched
        # write commits, instead of failing a profile sync with "database is
        # locked".
        conn = sqlite3.connect(self.db_path, timeout=30)
        conn.execute("PRAGMA busy_timeout = 30000")
        return conn

    def _init_db(self) -> None:
        with self._write_lock, closing(self._connect()) as conn:
            conn.execute("PRAGMA journal_mode = WAL")
            conn.execute("PRAGMA synchronous = NORMAL")
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
            conn.commit()

    def get(self, namespace: str, key: str, ttl: Optional[float] = None) -> Optional[Any]:
        """Return the cached value, or None if missing / expired."""
        entry = self.get_with_freshness(namespace, key, ttl=ttl)
        if entry is None:
            return None
        value, fresh = entry
        return value if fresh else None

    def get_with_freshness(
        self, namespace: str, key: str, ttl: Optional[float] = None
    ) -> Optional[tuple[Any, bool]]:
        """Return ``(value, fresh)`` without discarding an expired entry."""
        with closing(self._connect()) as conn:
            row = conn.execute(
                "SELECT value, created_at FROM cache WHERE namespace = ? AND key = ?",
                (namespace, str(key)),
            ).fetchone()
        if row is None:
            return None
        value, created_at = row
        fresh = ttl is None or (time.time() - created_at) <= ttl
        return json.loads(value), fresh

    def set(self, namespace: str, key: str, value: Any) -> None:
        """Store a JSON-serialisable value."""
        with self._write_lock, closing(self._connect()) as conn:
            conn.execute(
                """
                INSERT INTO cache (namespace, key, value, created_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT (namespace, key)
                DO UPDATE SET value = excluded.value, created_at = excluded.created_at
                """,
                (namespace, str(key), json.dumps(value), time.time()),
            )
            conn.commit()

    def get_many(
        self, namespace: str, keys: list[str], ttl: Optional[float] = None
    ) -> dict[str, Any]:
        if not keys:
            return {}
        placeholders = ",".join("?" for _ in keys)
        with closing(self._connect()) as conn:
            rows = conn.execute(
                f"SELECT key, value, created_at FROM cache "
                f"WHERE namespace = ? AND key IN ({placeholders})",
                (namespace, *[str(key) for key in keys]),
            ).fetchall()
        now = time.time()
        return {
            key: json.loads(value)
            for key, value, created_at in rows
            if ttl is None or (now - created_at) <= ttl
        }

    def set_many(self, namespace: str, values: dict[str, Any]) -> None:
        if not values:
            return
        created_at = time.time()
        rows = [
            (namespace, str(key), json.dumps(value), created_at)
            for key, value in values.items()
        ]
        with self._write_lock, closing(self._connect()) as conn:
            conn.executemany(
                """
                INSERT INTO cache (namespace, key, value, created_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT (namespace, key)
                DO UPDATE SET value = excluded.value, created_at = excluded.created_at
                """,
                rows,
            )
            conn.commit()

    def touch(self, namespace: str, key: str) -> bool:
        """Refresh an existing entry's timestamp without rewriting its value."""
        with self._write_lock, closing(self._connect()) as conn:
            cursor = conn.execute(
                "UPDATE cache SET created_at = ? WHERE namespace = ? AND key = ?",
                (time.time(), namespace, str(key)),
            )
            conn.commit()
            return cursor.rowcount > 0

    def delete(self, namespace: str, key: str) -> bool:
        """Idempotently delete one cache entry."""
        with self._write_lock, closing(self._connect()) as conn:
            conn.execute(
                "DELETE FROM cache WHERE namespace = ? AND key = ?",
                (namespace, str(key)),
            )
            conn.commit()
            return True

    def clear(self, namespace: Optional[str] = None) -> None:
        """Drop one namespace, or the whole cache when namespace is None."""
        with self._write_lock, closing(self._connect()) as conn:
            if namespace is None:
                conn.execute("DELETE FROM cache")
            else:
                conn.execute("DELETE FROM cache WHERE namespace = ?", (namespace,))
            conn.commit()


class LayeredCache:
    """Fast local L1 plus persistent remote L2 with batched remote writes."""

    def __init__(self, local: Cache, remote):
        self.local = local
        self.remote = remote
        self._pending: dict[tuple[str, str], Any] = {}
        self._pending_lock = threading.Lock()

    def get(self, namespace: str, key: str, ttl: Optional[float] = None) -> Optional[Any]:
        value = self.local.get(namespace, key, ttl=ttl)
        if value is not None:
            return value
        value = self.remote.get(namespace, key, ttl=ttl)
        if value is not None:
            self.local.set(namespace, key, value)
        return value

    def set(self, namespace: str, key: str, value: Any) -> None:
        self.local.set(namespace, key, value)
        with self._pending_lock:
            self._pending[(namespace, str(key))] = value

    def prefetch(self, namespace: str, keys: list[str], ttl: Optional[float] = None) -> int:
        """Hydrate missing L1 keys from L2 in bounded batches."""
        normalized = list(dict.fromkeys(str(key) for key in keys))
        local_values = self.local.get_many(namespace, normalized, ttl=ttl)
        missing = [key for key in normalized if key not in local_values]
        hydrated = 0
        for start in range(0, len(missing), 100):
            remote_values = self.remote.get_many(
                namespace, missing[start:start + 100], ttl=ttl
            )
            self.local.set_many(namespace, remote_values)
            hydrated += len(remote_values)
        return hydrated

    def flush(self) -> int:
        """Persist queued L1 mutations to L2 using namespace batches."""
        with self._pending_lock:
            pending = self._pending
            self._pending = {}
        grouped: dict[str, dict[str, Any]] = defaultdict(dict)
        for (namespace, key), value in pending.items():
            grouped[namespace][key] = value
        persisted = 0
        failed: dict[tuple[str, str], Any] = {}
        for namespace, values in grouped.items():
            success = self.remote.set_many(namespace, values)
            if success is False:
                failed.update(((namespace, key), value) for key, value in values.items())
            else:
                persisted += len(values)
        if failed:
            # Keep failed L2 writes queued; a later request can retry them.
            with self._pending_lock:
                failed.update(self._pending)
                self._pending = failed
        return persisted
