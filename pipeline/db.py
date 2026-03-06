"""Turso/libsql connection helper.

Includes WAL mode, busy timeout, and retry logic for robust
concurrent access between the signal bot and cron collection scripts.
"""

import time
import logging
import libsql_experimental as libsql
from config import TURSO_DB_URL, TURSO_AUTH_TOKEN

log = logging.getLogger(__name__)


def get_connection(retries: int = 3):
    """Create a new DB connection with WAL mode and busy timeout."""
    if TURSO_AUTH_TOKEN:
        conn = libsql.connect(
            "bittensor_edge.db",
            sync_url=TURSO_DB_URL,
            auth_token=TURSO_AUTH_TOKEN,
        )
        for attempt in range(retries):
            try:
                conn.sync()
                break
            except (ValueError, Exception) as e:
                err = str(e).lower()
                if ("locked" in err or "wal" in err) and attempt < retries - 1:
                    time.sleep(2 * (attempt + 1))
                    continue
                raise
        # Set WAL mode and busy timeout for concurrent access
        try:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA busy_timeout=30000")
        except Exception:
            pass  # Some libsql versions may not support these
        return conn
    return libsql.connect(TURSO_DB_URL)


def get_connection_with_retry(max_retries: int = 3):
    """Create a new DB connection with full retry logic.

    Creates a completely new connection object on each failure attempt.
    Tests the connection with a simple query before returning.
    Sets WAL mode and busy timeout for concurrent access.
    """
    last_error = None
    for attempt in range(max_retries):
        try:
            conn = get_connection()
            # Test the connection is actually working
            conn.execute("SELECT 1")
            return conn
        except Exception as e:
            last_error = e
            log.warning(f"DB connection attempt {attempt + 1}/{max_retries} failed: {e}")
            if attempt < max_retries - 1:
                time.sleep(5 * (attempt + 1))  # 5s, 10s, 15s backoff
    raise ConnectionError(
        f"Failed to connect to Turso after {max_retries} attempts. Last error: {last_error}"
    )


def safe_sync(conn, retries: int = 3):
    """Sync with retry for WAL lock contention between threads."""
    for attempt in range(retries):
        try:
            conn.sync()
            return True
        except (ValueError, Exception) as e:
            err = str(e).lower()
            if ("locked" in err or "wal" in err or "stream" in err) and attempt < retries - 1:
                time.sleep(2 * (attempt + 1))
                continue
            raise
    return False
