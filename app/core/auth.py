"""API Key authentication and usage tracking for Cerebrum Blocks."""

import hashlib
import hmac
import logging
import os
import re
import sqlite3
import sys
import threading
import time
from typing import Optional, Dict, Any

from fastapi import HTTPException
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials


logger = logging.getLogger(__name__)


_KEY_DIGEST_RE = re.compile(r"^[0-9a-f]{64}$")


class _UsageStore:
    """Hour-bucketed usage counter shared across processes.

    Backed by SQLite in WAL mode at $DATA_DIR/rate_limits.db when DATA_DIR
    is writable; falls back to a process-local dict otherwise. The
    previous in-memory-only implementation reset on every worker restart
    and let multi-worker deployments multiply the limit by `n` (each
    worker had an independent counter). With SQLite WAL the upsert is
    atomic across processes on the same host.

    The rows are keyed by a salted SHA-256 digest of the API key, never
    the key itself. The audit found the previous version used the bearer
    credential verbatim as the primary key, so every live key — including
    CEREBRUM_MASTER_KEY — was recoverable by reading the database file off
    the persistent disk. Rate limiting needs a stable opaque identifier,
    not the plaintext, so hashing is behaviour-preserving.

    The salt is random per database and persisted in a `meta` table. It
    defeats precomputed-digest lookups against a low-entropy operator-
    chosen master key; it is not a secret and does not need protecting.
    """

    def __init__(self):
        self._lock = threading.Lock()
        self._mem: Dict[str, Dict[int, int]] = {}
        self._db_path: Optional[str] = None
        self._salt: str = os.urandom(16).hex()
        self._setup_db()

    def _setup_db(self) -> None:
        data_dir = os.getenv("DATA_DIR", "./data")
        try:
            os.makedirs(data_dir, exist_ok=True)
            path = os.path.join(data_dir, "rate_limits.db")
            with sqlite3.connect(path, timeout=2.0) as conn:
                conn.execute("PRAGMA journal_mode=WAL")
                conn.execute(
                    "CREATE TABLE IF NOT EXISTS usage("
                    "  key TEXT NOT NULL, "
                    "  hour_bucket INTEGER NOT NULL, "
                    "  count INTEGER NOT NULL DEFAULT 0, "
                    "  PRIMARY KEY (key, hour_bucket))"
                )
                conn.execute(
                    "CREATE TABLE IF NOT EXISTS meta("
                    "  k TEXT PRIMARY KEY, v TEXT NOT NULL)"
                )
                conn.execute(
                    "INSERT OR IGNORE INTO meta(k, v) VALUES('key_salt', ?)",
                    (self._salt,),
                )
                row = conn.execute(
                    "SELECT v FROM meta WHERE k='key_salt'"
                ).fetchone()
                if row and row[0]:
                    self._salt = str(row[0])
            self._db_path = path
            self._purge_plaintext_keys(path)
        except (OSError, sqlite3.Error) as exc:
            logger.warning(
                "rate_limit: SQLite backend unavailable (%s) — falling back "
                "to in-memory counter; multi-worker bypass possible.", exc,
            )
            self._db_path = None

    @staticmethod
    def _purge_plaintext_keys(path: str) -> None:
        """Remove pre-hash rows and scrub them from the file's free pages.

        Databases written by the previous version hold raw API keys in
        `usage.key`. Those rows are hour-bucketed counters, so dropping
        them costs at most one hour of accumulated count — cheaper than
        carrying recoverable credentials on disk. DELETE alone leaves the
        plaintext in freed pages and in the write-ahead log, so the purge
        is followed by VACUUM (rebuilds the main file) and a truncating
        WAL checkpoint (zeroes the -wal file).
        """
        try:
            conn = sqlite3.connect(path, timeout=5.0, isolation_level=None)
        except sqlite3.Error:
            return
        try:
            # The table is pruned hourly, so this stays small. Detect
            # pre-hash rows in Python rather than with a 64-element SQL
            # GLOB: anything that is not a lowercase 64-hex digest was
            # written by the plaintext-key version.
            legacy = sum(
                1
                for (stored,) in conn.execute("SELECT key FROM usage")
                if not _KEY_DIGEST_RE.match(str(stored))
            )
            if not legacy:
                return
            logger.warning(
                "rate_limit: purging %d plaintext API key row(s) from %s "
                "(pre-hash schema); counters for the current hour reset.",
                legacy, os.path.basename(path),
            )
            conn.execute("DELETE FROM usage")
            conn.execute("VACUUM")
            conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        except sqlite3.Error as exc:
            logger.warning("rate_limit: plaintext-key purge failed (%s)", exc)
        finally:
            try:
                conn.close()
            except sqlite3.Error:
                pass

    def _digest(self, key: str) -> str:
        """Stable opaque identifier for an API key. Never reversible."""
        return hashlib.sha256(
            (self._salt + ":" + (key or "")).encode("utf-8")
        ).hexdigest()

    def increment(self, key: str, hour_bucket: int) -> int:
        digest = self._digest(key)
        if self._db_path:
            try:
                with sqlite3.connect(self._db_path, timeout=2.0) as conn:
                    conn.execute(
                        "INSERT INTO usage(key, hour_bucket, count) VALUES(?, ?, 1) "
                        "ON CONFLICT(key, hour_bucket) DO UPDATE SET count = count + 1",
                        (digest, hour_bucket),
                    )
                    row = conn.execute(
                        "SELECT count FROM usage WHERE key=? AND hour_bucket=?",
                        (digest, hour_bucket),
                    ).fetchone()
                    return int(row[0]) if row else 0
            except sqlite3.Error as exc:
                logger.warning("rate_limit: SQLite write failed (%s)", exc)
                # fall through to memory backup
        with self._lock:
            self._mem.setdefault(digest, {})
            self._mem[digest][hour_bucket] = self._mem[digest].get(hour_bucket, 0) + 1
            return self._mem[digest][hour_bucket]

    def get(self, key: str, hour_bucket: int) -> int:
        digest = self._digest(key)
        if self._db_path:
            try:
                with sqlite3.connect(self._db_path, timeout=2.0) as conn:
                    row = conn.execute(
                        "SELECT count FROM usage WHERE key=? AND hour_bucket=?",
                        (digest, hour_bucket),
                    ).fetchone()
                    return int(row[0]) if row else 0
            except sqlite3.Error:
                pass
        with self._lock:
            return self._mem.get(digest, {}).get(hour_bucket, 0)

    def prune_older_than(self, hour_bucket: int) -> None:
        """Drop counters strictly older than `hour_bucket`. Cheap to call
        once per request — SQLite does the work without scanning."""
        if self._db_path:
            try:
                with sqlite3.connect(self._db_path, timeout=2.0) as conn:
                    conn.execute("DELETE FROM usage WHERE hour_bucket < ?", (hour_bucket,))
            except sqlite3.Error:
                pass
        with self._lock:
            for k in list(self._mem):
                self._mem[k] = {h: c for h, c in self._mem[k].items() if h >= hour_bucket}
                if not self._mem[k]:
                    del self._mem[k]


class APIKeyAuth:
    """API key authentication with usage tracking and periodic env reload."""

    def __init__(self):
        self.security = HTTPBearer(auto_error=False)
        self._keys: Dict[str, Dict] = {}
        self._keys_loaded_at: float = 0.0
        self._reload_ttl = float(os.getenv("API_KEYS_RELOAD_TTL", "60"))
        self._usage = _UsageStore()
        self._reload_keys()

    @staticmethod
    def _is_dev_environment() -> bool:
        # Single source of truth: ENV / ENVIRONMENT env vars. The previous
        # version also returned True if `pytest` was anywhere in sys.modules,
        # which incorrectly triggers when a worker has pytest preloaded for
        # any reason — silently activating the cb_dev_key in production.
        env = os.getenv("ENV", os.getenv("ENVIRONMENT", "production")).strip().lower()
        return env in {"dev", "development", "local", "test", "testing"}

    def _load_keys(self) -> Dict[str, Dict]:
        keys: Dict[str, Dict] = {}

        if self._is_dev_environment():
            keys["cb_dev_key"] = {
                "user": "dev",
                "tier": "unlimited",
                "role": "admin",
                "rate_limit": float('inf'),
                "created_at": time.time(),
            }

        master = os.getenv("CEREBRUM_MASTER_KEY")
        if master:
            keys[master] = {
                "user": "master",
                "tier": "unlimited",
                "role": "admin",
                "rate_limit": float('inf'),
                "created_at": time.time(),
            }

        for k, v in os.environ.items():
            if k.startswith("CEREBRUM_API_KEY_") and v:
                keys[v] = {
                    "user": k.replace("CEREBRUM_API_KEY_", "").lower(),
                    "tier": "standard",
                    "role": "user",
                    "rate_limit": 1000,
                    "created_at": time.time(),
                }

        return keys

    def _reload_keys(self) -> None:
        self._keys = self._load_keys()
        self._keys_loaded_at = time.time()
        logger.info("auth: loaded %d API key(s)", len(self._keys))

    def _maybe_reload(self) -> None:
        if self._reload_ttl > 0 and time.time() - self._keys_loaded_at > self._reload_ttl:
            self._reload_keys()

    def reload(self) -> None:
        """Force an immediate key reload from environment."""
        self._reload_keys()

    def validate_key(self, credentials: Optional[HTTPAuthorizationCredentials]) -> Dict[str, Any]:
        if not credentials:
            raise HTTPException(status_code=401, detail="API key required.")

        self._maybe_reload()

        key = credentials.credentials

        # Constant-time match against every loaded key. dict-membership
        # leaks timing on long shared prefixes; hmac.compare_digest does
        # not. Cost is O(N keys × len(longest)) per request — fine for
        # the small key set this service runs (single-digit count).
        matched = None
        for known in self._keys:
            if hmac.compare_digest(key, known):
                matched = known
                break
        if matched is None:
            raise HTTPException(status_code=401, detail="Invalid API key")

        key_data = self._keys[matched].copy()
        key_data["valid"] = True
        # Default role for legacy entries — unlimited keys without a role
        # are treated as admin (master keys), standard keys as user.
        if "role" not in key_data:
            key_data["role"] = "admin" if key_data.get("tier") == "unlimited" else "user"

        current_count = self._track_usage(matched)

        if self._is_rate_limited(matched, key_data.get("rate_limit", 100), current_count):
            raise HTTPException(status_code=429, detail="Rate limit exceeded.")

        return key_data

    def _track_usage(self, key: str) -> int:
        """Increment and return usage count for the current hour bucket."""
        hour_bucket = int(time.time() / 3600)
        # Opportunistic prune: keeps the table size bounded with no extra
        # background job. Older-than-current-hour rows are not consulted
        # by the limiter.
        self._usage.prune_older_than(hour_bucket)
        return self._usage.increment(key, hour_bucket)

    def _is_rate_limited(self, key: str, limit: float, current_count: Optional[int] = None) -> bool:
        """Check if key is rate limited."""
        if limit == float('inf'):
            return False
        if current_count is None:
            current_count = self._usage.get(key, int(time.time() / 3600))
        return current_count > limit

    def get_usage(self, key: str) -> Dict[str, Any]:
        """Get usage stats for a key."""
        hour_bucket = int(time.time() / 3600)
        return {
            "requests_this_hour": self._usage.get(key, hour_bucket),
            "rate_limit": self._keys.get(key, {}).get("rate_limit", 100),
            "tier": self._keys.get(key, {}).get("tier", "free"),
        }


# Global auth instance
auth = APIKeyAuth()
