"""Turso/libsql connection helper."""

import libsql_experimental as libsql
from config import TURSO_DB_URL, TURSO_AUTH_TOKEN


def get_connection():
    if TURSO_AUTH_TOKEN:
        conn = libsql.connect(
            "bittensor_edge.db",
            sync_url=TURSO_DB_URL,
            auth_token=TURSO_AUTH_TOKEN,
        )
        conn.sync()
        return conn
    return libsql.connect(TURSO_DB_URL)
