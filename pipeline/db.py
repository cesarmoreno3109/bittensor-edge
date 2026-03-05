"""Turso/libsql connection helper."""

import time
import libsql_experimental as libsql
from config import TURSO_DB_URL, TURSO_AUTH_TOKEN


def get_connection(retries: int = 3):
    if TURSO_AUTH_TOKEN:
        conn = libsql.connect(
            "bittensor_edge.db",
            sync_url=TURSO_DB_URL,
            auth_token=TURSO_AUTH_TOKEN,
        )
        for attempt in range(retries):
            try:
                conn.sync()
                return conn
            except ValueError as e:
                if "database is locked" in str(e) and attempt < retries - 1:
                    time.sleep(1 + attempt)
                    continue
                raise
        return conn
    return libsql.connect(TURSO_DB_URL)


def safe_sync(conn, retries: int = 3):
    """Sync with retry for WAL lock contention between threads."""
    for attempt in range(retries):
        try:
            conn.sync()
            return True
        except ValueError as e:
            if "database is locked" in str(e) and attempt < retries - 1:
                time.sleep(1 + attempt)
                continue
            raise
    return False
