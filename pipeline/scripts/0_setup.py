#!/usr/bin/env python3
"""Phase 0: Setup — Create DB schema, verify API connectivity."""

import sys
import os
import time
import requests

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from datetime import datetime, timezone


def log(msg: str):
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    print(f"[{ts}] {msg}")


# ── DB Schema ─────────────────────────────────────────────────────────────────

SCHEMA_SQL = [
    """CREATE TABLE IF NOT EXISTS tao_prices (
        timestamp INTEGER PRIMARY KEY,
        open REAL,
        high REAL,
        low REAL,
        close REAL,
        volume REAL,
        source TEXT
    )""",
    """CREATE TABLE IF NOT EXISTS subnet_info (
        snapshot_ts INTEGER,
        subnet_id INTEGER,
        emission_rate REAL,
        validator_count INTEGER,
        total_stake REAL,
        PRIMARY KEY (snapshot_ts, subnet_id)
    )""",
    """CREATE TABLE IF NOT EXISTS validator_weights (
        snapshot_ts INTEGER,
        validator_hotkey TEXT,
        subnet_id INTEGER,
        weight REAL,
        PRIMARY KEY (snapshot_ts, validator_hotkey, subnet_id)
    )""",
    """CREATE TABLE IF NOT EXISTS staking_events (
        block_num INTEGER PRIMARY KEY,
        timestamp INTEGER,
        event_type TEXT,
        subnet_id INTEGER,
        amount REAL,
        hotkey TEXT
    )""",
    """CREATE TABLE IF NOT EXISTS api_status (
        api_name TEXT PRIMARY KEY,
        status TEXT,
        latency_ms INTEGER,
        last_checked INTEGER,
        error_msg TEXT
    )""",
    """CREATE TABLE IF NOT EXISTS raw_responses (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        source TEXT,
        endpoint TEXT,
        timestamp INTEGER,
        response_json TEXT
    )""",
    """CREATE TABLE IF NOT EXISTS analysis_reports (
        timestamp INTEGER PRIMARY KEY,
        report_json TEXT
    )""",
]


def create_schema():
    from db import get_connection

    log("Creating database schema...")
    conn = get_connection()
    for sql in SCHEMA_SQL:
        conn.execute(sql)
    conn.commit()
    conn.sync()
    log("Database schema created (7 tables).")
    return conn


# ── API Verification ──────────────────────────────────────────────────────────

def check_api(name: str, method: str, url: str, **kwargs) -> dict:
    start = time.time()
    try:
        if method == "GET":
            resp = requests.get(url, timeout=15, **kwargs)
        else:
            resp = requests.post(url, timeout=15, **kwargs)
        latency_ms = int((time.time() - start) * 1000)
        if resp.status_code == 200:
            return {"status": "ok", "latency_ms": latency_ms, "error_msg": ""}
        return {
            "status": "error",
            "latency_ms": latency_ms,
            "error_msg": f"HTTP {resp.status_code}: {resp.text[:200]}",
        }
    except Exception as e:
        latency_ms = int((time.time() - start) * 1000)
        return {"status": "error", "latency_ms": latency_ms, "error_msg": str(e)[:200]}


def verify_apis(conn):
    from config import COINGECKO_BASE, SUBSCAN_BASE, TAOSTATS_BASE, RPC_ENDPOINT

    log("Verifying API connectivity...")

    apis = [
        ("CoinGecko", "GET", f"{COINGECKO_BASE}/ping", {}),
        ("Subscan", "POST", f"{SUBSCAN_BASE}/scan/metadata", {"json": {}}),
        ("TaoStats", "GET", f"{TAOSTATS_BASE}/subnet/latest", {}),
        (
            "Bittensor RPC",
            "POST",
            RPC_ENDPOINT,
            {"json": {"method": "system_health", "params": [], "id": 1, "jsonrpc": "2.0"}},
        ),
    ]

    now_ts = int(time.time())

    print("\n" + "=" * 65)
    print(f"{'API':<18} {'Status':<8} {'Latency':<10} {'Error'}")
    print("-" * 65)

    for name, method, url, kwargs in apis:
        r = check_api(name, method, url, **kwargs)
        icon = "OK" if r["status"] == "ok" else "FAIL"
        err = r["error_msg"][:35] if r["error_msg"] else ""
        print(f"{name:<18} {icon:<8} {r['latency_ms']:>5}ms    {err}")

        conn.execute(
            """INSERT OR REPLACE INTO api_status
               (api_name, status, latency_ms, last_checked, error_msg)
               VALUES (?, ?, ?, ?, ?)""",
            (name, r["status"], r["latency_ms"], now_ts, r["error_msg"]),
        )
        time.sleep(0.5)

    conn.commit()
    conn.sync()
    print("=" * 65)


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    print("\n" + "=" * 65)
    print("BITTENSOR EDGE — PHASE 0: SETUP")
    print("=" * 65 + "\n")

    conn = create_schema()
    verify_apis(conn)
    conn.close()
    log("Phase 0 complete.")


if __name__ == "__main__":
    main()
