#!/usr/bin/env python3
"""Phase 5: Collect real on-chain subnet data from TaoStats API.

Rate limit: STRICT 4 requests/minute (15s between EVERY request).
API docs: https://api.taostats.io
"""

import sys
import os
import time
import json
import requests
from datetime import datetime, timezone
from collections import deque

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config import (
    TAOSTATS_BASE,
    TAOSTATS_API_KEY,
    TAOSTATS_RATE_LIMIT_SECONDS,
    TOP_SUBNETS_DETAILED,
)


def log(msg: str):
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    print(f"[{ts}] {msg}")


# ── DB Schema (new tables) ────────────────────────────────────────────────────

TAOSTATS_SCHEMA = [
    """CREATE TABLE IF NOT EXISTS taostats_subnets (
        snapshot_ts INTEGER,
        netuid INTEGER,
        name TEXT,
        emission_pct REAL,
        price_tao REAL,
        price_usd REAL,
        market_cap_tao REAL,
        market_cap_usd REAL,
        volume_24h_tao REAL,
        total_stake_tao REAL,
        validator_count INTEGER,
        miner_count INTEGER,
        tao_flow_24h REAL,
        tao_flow_7d REAL,
        tao_flow_30d REAL,
        registration_cost REAL,
        ema_tao_flow REAL,
        active_keys INTEGER,
        tempo INTEGER,
        emission_raw REAL,
        PRIMARY KEY(snapshot_ts, netuid)
    )""",
    """CREATE TABLE IF NOT EXISTS taostats_validators (
        snapshot_ts INTEGER,
        netuid INTEGER,
        hotkey TEXT,
        coldkey TEXT,
        name TEXT,
        stake_tao REAL,
        nominators INTEGER,
        dominance REAL,
        take REAL,
        rank INTEGER,
        is_active INTEGER,
        PRIMARY KEY(snapshot_ts, netuid, hotkey)
    )""",
    """CREATE TABLE IF NOT EXISTS taostats_subnet_pools (
        snapshot_ts INTEGER,
        netuid INTEGER,
        tao_in REAL,
        alpha_in REAL,
        alpha_out REAL,
        price REAL,
        PRIMARY KEY(snapshot_ts, netuid)
    )""",
    """CREATE TABLE IF NOT EXISTS taostats_deregistration_risk (
        snapshot_ts INTEGER,
        netuid INTEGER,
        name TEXT,
        ema_price REAL,
        rank INTEGER,
        is_at_risk INTEGER,
        PRIMARY KEY(snapshot_ts, netuid)
    )""",
    """CREATE TABLE IF NOT EXISTS taostats_network_stats (
        timestamp INTEGER PRIMARY KEY,
        total_stake REAL,
        total_subnets INTEGER,
        total_validators INTEGER,
        total_miners INTEGER,
        difficulty REAL,
        block_number INTEGER,
        tao_supply REAL
    )""",
    """CREATE TABLE IF NOT EXISTS taostats_tao_flow (
        snapshot_ts INTEGER,
        netuid INTEGER,
        tao_flow REAL,
        PRIMARY KEY(snapshot_ts, netuid)
    )""",
]


def create_taostats_schema(conn):
    log("Creating TaoStats tables...")
    for sql in TAOSTATS_SCHEMA:
        conn.execute(sql)
    conn.commit()
    conn.sync()
    log(f"TaoStats schema ready ({len(TAOSTATS_SCHEMA)} tables).")


# ── TaoStats API Client ──────────────────────────────────────────────────────

class TaoStatsClient:
    """Client for TaoStats API with strict rate limiting."""

    def __init__(self, api_key: str):
        self.api_key = api_key
        self.base_url = TAOSTATS_BASE
        self.headers = {"Authorization": api_key}
        self.rate_limit_seconds = TAOSTATS_RATE_LIMIT_SECONDS
        # Track last 4 request timestamps for sliding window enforcement
        self._request_times: deque = deque(maxlen=4)
        self._total_requests = 0

    def _enforce_rate_limit(self):
        """Ensure we never exceed 4 requests in any 60-second window."""
        now = time.time()

        # Always sleep at least rate_limit_seconds between requests
        if self._request_times:
            elapsed = now - self._request_times[-1]
            if elapsed < self.rate_limit_seconds:
                wait = self.rate_limit_seconds - elapsed
                log(f"  Rate limit: waiting {wait:.1f}s...")
                time.sleep(wait)

        # Extra safety: if 4 requests in last 60s, wait until window clears
        if len(self._request_times) >= 4:
            window_start = self._request_times[0]
            window_elapsed = time.time() - window_start
            if window_elapsed < 60:
                wait = 60 - window_elapsed + 1
                log(f"  Rate limit window: waiting {wait:.1f}s...")
                time.sleep(wait)

    def _get(self, endpoint: str, params: dict = None, max_retries: int = 3) -> dict | None:
        """Generic GET with auth header, rate limiting, and retry."""
        self._enforce_rate_limit()

        url = f"{self.base_url}/{endpoint}"
        for attempt in range(max_retries):
            try:
                self._request_times.append(time.time())
                self._total_requests += 1
                resp = requests.get(url, headers=self.headers, params=params, timeout=30)

                if resp.status_code == 200:
                    return resp.json()
                elif resp.status_code == 429:
                    wait = 30 * (2 ** attempt)
                    log(f"  429 Rate limited. Backing off {wait}s (attempt {attempt+1}/{max_retries})")
                    time.sleep(wait)
                    continue
                elif resp.status_code == 404:
                    log(f"  404 Not found: {endpoint} (skipping)")
                    return None
                else:
                    log(f"  HTTP {resp.status_code} for {endpoint}: {resp.text[:100]}")
                    if attempt < max_retries - 1:
                        wait = 30 * (2 ** attempt)
                        log(f"  Retrying in {wait}s...")
                        time.sleep(wait)
            except requests.exceptions.Timeout:
                log(f"  Timeout for {endpoint} (attempt {attempt+1}/{max_retries})")
                if attempt < max_retries - 1:
                    time.sleep(30 * (2 ** attempt))
            except Exception as e:
                log(f"  Error for {endpoint}: {e}")
                if attempt < max_retries - 1:
                    time.sleep(30 * (2 ** attempt))

        log(f"  FAILED after {max_retries} attempts: {endpoint}")
        return None

    # ── Endpoint methods ──────────────────────────────────────────────────

    def verify_key(self) -> bool:
        """Verify API key works."""
        data = self._get("api/price/latest/v1", params={"asset": "tao"})
        if data and "data" in data and len(data["data"]) > 0:
            price = data["data"][0].get("price", "?")
            log(f"  API key verified. Current TAO price: ${float(price):.2f}")
            return True
        log("  API key verification FAILED!")
        return False

    def get_subnets_latest(self) -> list:
        """Get latest snapshot of all subnets."""
        data = self._get("api/subnet/latest/v1")
        if data and "data" in data:
            return data["data"]
        return []

    def get_tao_flow(self) -> list:
        """Get TAO flow across all subnets."""
        data = self._get("api/dtao/tao_flow/v1")
        if data and "data" in data:
            return data["data"]
        return []

    def get_price_latest(self) -> dict | None:
        """Get current TAO price."""
        data = self._get("api/price/latest/v1", params={"asset": "tao"})
        if data and "data" in data and len(data["data"]) > 0:
            return data["data"][0]
        return None

    def get_validators(self, netuid: int) -> list:
        """Get validators for a specific subnet."""
        data = self._get("api/validator/latest/v1", params={"netuid": netuid})
        if data and "data" in data:
            return data["data"]
        return []

    def get_metagraph(self, netuid: int) -> list:
        """Get metagraph for a specific subnet."""
        data = self._get("api/metagraph/latest/v1", params={"netuid": netuid})
        if data and "data" in data:
            return data["data"]
        return []

    def get_burned_alpha_total(self) -> dict | None:
        """Get total burned alpha data."""
        data = self._get("api/dtao/burned_alpha/total/v1")
        if data and "data" in data:
            return data["data"]
        return None


# ── Data Insertion Helpers ────────────────────────────────────────────────────

def _to_float(val, scale: float = 1e-9) -> float | None:
    """Convert string/int values to float, optionally scaling from rao."""
    if val is None:
        return None
    try:
        f = float(val)
        if abs(f) > 1e15:  # Likely in rao (1e-9 TAO)
            return f * 1e-9
        return f
    except (ValueError, TypeError):
        return None


def insert_subnets(conn, subnets: list, snapshot_ts: int):
    """Insert subnet data into taostats_subnets."""
    count = 0
    for s in subnets:
        netuid = s.get("netuid")
        if netuid is None:
            continue

        # Extract name from owner_hotkey or just use netuid
        name = s.get("name", f"Subnet {netuid}")
        if isinstance(name, dict):
            name = f"Subnet {netuid}"

        emission_raw = _to_float(s.get("emission"))
        projected_emission = _to_float(s.get("projected_emission"))
        ema_flow = _to_float(s.get("ema_tao_flow"))

        # Net flows are already in reasonable units if < 1e15, else rao
        flow_1d = _to_float(s.get("net_flow_1_day"))
        flow_7d = _to_float(s.get("net_flow_7_days"))
        flow_30d = _to_float(s.get("net_flow_30_days"))

        reg_cost = _to_float(s.get("registration_cost"))

        conn.execute(
            """INSERT OR REPLACE INTO taostats_subnets
               (snapshot_ts, netuid, name, emission_pct, price_tao, price_usd,
                market_cap_tao, market_cap_usd, volume_24h_tao, total_stake_tao,
                validator_count, miner_count, tao_flow_24h, tao_flow_7d, tao_flow_30d,
                registration_cost, ema_tao_flow, active_keys, tempo, emission_raw)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                snapshot_ts,
                netuid,
                name,
                projected_emission,   # emission as percentage
                None,                 # price_tao — not in this endpoint
                None,                 # price_usd — not in this endpoint
                None,                 # market_cap_tao
                None,                 # market_cap_usd
                None,                 # volume_24h_tao
                None,                 # total_stake_tao
                s.get("validators") or s.get("active_validators", 0),
                s.get("active_miners", 0),
                flow_1d,
                flow_7d,
                flow_30d,
                reg_cost,
                ema_flow,
                s.get("active_keys", 0),
                s.get("tempo", 0),
                emission_raw,
            ),
        )
        count += 1
    conn.commit()
    return count


def insert_tao_flow(conn, flows: list, snapshot_ts: int):
    """Insert TAO flow data."""
    count = 0
    for f in flows:
        netuid = f.get("netuid")
        if netuid is None:
            continue
        tao_flow = _to_float(f.get("tao_flow"))
        conn.execute(
            """INSERT OR REPLACE INTO taostats_tao_flow
               (snapshot_ts, netuid, tao_flow)
               VALUES (?,?,?)""",
            (snapshot_ts, netuid, tao_flow),
        )
        count += 1
    conn.commit()
    return count


def insert_validators(conn, validators: list, netuid: int, snapshot_ts: int):
    """Insert validator data for a subnet."""
    count = 0
    for v in validators:
        hotkey_data = v.get("hotkey", {})
        coldkey_data = v.get("coldkey", {})
        hotkey = hotkey_data.get("ss58", "") if isinstance(hotkey_data, dict) else str(hotkey_data)
        coldkey = coldkey_data.get("ss58", "") if isinstance(coldkey_data, dict) else str(coldkey_data)

        stake = _to_float(v.get("stake"))
        if stake is None:
            stake = _to_float(v.get("system_stake"))

        conn.execute(
            """INSERT OR REPLACE INTO taostats_validators
               (snapshot_ts, netuid, hotkey, coldkey, name, stake_tao,
                nominators, dominance, take, rank, is_active)
               VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
            (
                snapshot_ts,
                netuid,
                hotkey,
                coldkey,
                v.get("name", ""),
                stake,
                v.get("nominators", 0),
                _to_float(v.get("dominance")),
                _to_float(v.get("take")),
                v.get("rank", 0),
                1,  # is_active (they're in the latest list)
            ),
        )
        count += 1
    conn.commit()
    return count


def insert_network_stats(conn, subnets: list, tao_price: float, snapshot_ts: int):
    """Compute and insert network-level stats from subnet data."""
    total_validators = sum(s.get("active_validators", 0) or 0 for s in subnets)
    total_miners = sum(s.get("active_miners", 0) or 0 for s in subnets)
    total_keys = sum(s.get("active_keys", 0) or 0 for s in subnets)

    # Find max block number
    block_number = max((s.get("block_number", 0) or 0 for s in subnets), default=0)

    conn.execute(
        """INSERT OR REPLACE INTO taostats_network_stats
           (timestamp, total_stake, total_subnets, total_validators,
            total_miners, difficulty, block_number, tao_supply)
           VALUES (?,?,?,?,?,?,?,?)""",
        (
            snapshot_ts,
            None,           # total_stake — not easily available
            len(subnets),
            total_validators,
            total_miners,
            None,           # difficulty
            block_number,
            None,           # tao_supply
        ),
    )
    conn.commit()
    return 1


def save_raw_response(conn, source: str, endpoint: str, data, snapshot_ts: int):
    """Save raw API response for debugging."""
    try:
        conn.execute(
            """INSERT INTO raw_responses (source, endpoint, timestamp, response_json)
               VALUES (?,?,?,?)""",
            (source, endpoint, snapshot_ts, json.dumps(data)[:50000]),
        )
        conn.commit()
    except Exception as e:
        log(f"  Warning: couldn't save raw response: {e}")


# ── Subnet rotation logic ────────────────────────────────────────────────────

def get_rotation_group(conn, subnets: list, top_n: int = TOP_SUBNETS_DETAILED) -> list:
    """Pick which subnets to get detailed validator data for this run.

    Strategy: sort by emission (descending), then rotate through groups.
    Check which subnets have the OLDEST validator data and prioritize those.
    """
    # Sort subnets by emission descending
    def emission_key(s):
        e = s.get("projected_emission") or s.get("emission") or 0
        try:
            return float(e)
        except (ValueError, TypeError):
            return 0

    sorted_subnets = sorted(subnets, key=emission_key, reverse=True)

    # Check last validator data for each subnet
    try:
        res = conn.execute(
            "SELECT netuid, MAX(snapshot_ts) as last_ts FROM taostats_validators GROUP BY netuid"
        )
        last_collected = {int(r[0]): int(r[1]) for r in res.fetchall()}
    except Exception:
        last_collected = {}

    # Prioritize: subnets with no data, then oldest data, then top by emission
    no_data = [s for s in sorted_subnets if s.get("netuid") not in last_collected]
    has_data = [s for s in sorted_subnets if s.get("netuid") in last_collected]
    has_data.sort(key=lambda s: last_collected.get(s.get("netuid"), 0))

    selected = (no_data + has_data)[:top_n]
    return selected


# ── Main Collection Flow ─────────────────────────────────────────────────────

def main():
    print("\n" + "=" * 70)
    print("BITTENSOR EDGE — PHASE 5: TAOSTATS COLLECTION")
    print("=" * 70 + "\n")

    if not TAOSTATS_API_KEY:
        log("ERROR: TAOSTATS_API_KEY not set in .env!")
        sys.exit(1)

    from db import get_connection
    conn = get_connection()

    # Create tables if needed
    create_taostats_schema(conn)

    client = TaoStatsClient(TAOSTATS_API_KEY)
    snapshot_ts = int(time.time())
    errors = []

    # ── Step a: Verify API key ────────────────────────────────────────────
    log("Step 1/7: Verifying API key...")
    if not client.verify_key():
        log("FATAL: API key invalid. Exiting.")
        sys.exit(1)

    # ── Step b: Collect ALL subnets latest ────────────────────────────────
    log("Step 2/7: Collecting all subnets...")
    subnets = client.get_subnets_latest()
    if subnets:
        n = insert_subnets(conn, subnets, snapshot_ts)
        conn.sync()
        save_raw_response(conn, "taostats", "subnet/latest", {"count": len(subnets)}, snapshot_ts)
        log(f"  -> {n} subnets collected")
    else:
        errors.append("Failed to collect subnets")
        log("  ERROR: No subnet data returned")

    # ── Step c: Collect TAO flow ──────────────────────────────────────────
    log("Step 3/7: Collecting TAO flow...")
    flows = client.get_tao_flow()
    if flows:
        n = insert_tao_flow(conn, flows, snapshot_ts)
        conn.sync()
        log(f"  -> {n} TAO flow entries")
    else:
        log("  No TAO flow data (endpoint may be unavailable)")

    # ── Step d: Collect TAO price ─────────────────────────────────────────
    log("Step 4/7: Collecting TAO price...")
    price_data = client.get_price_latest()
    tao_price = 0.0
    if price_data:
        tao_price = float(price_data.get("price", 0))
        log(f"  -> TAO price: ${tao_price:.2f}")
        log(f"     Market cap: ${float(price_data.get('market_cap', 0)):,.0f}")
        log(f"     24h volume: ${float(price_data.get('volume_24h', 0)):,.0f}")
    else:
        errors.append("Failed to collect price")

    # ── Step e: Compute network stats ─────────────────────────────────────
    log("Step 5/7: Computing network stats...")
    if subnets:
        insert_network_stats(conn, subnets, tao_price, snapshot_ts)
        conn.sync()
        total_v = sum(s.get("active_validators", 0) or 0 for s in subnets)
        total_m = sum(s.get("active_miners", 0) or 0 for s in subnets)
        log(f"  -> {len(subnets)} subnets, {total_v} validators, {total_m} miners")

    # ── Step f: Collect burned alpha ──────────────────────────────────────
    log("Step 6/7: Collecting burned alpha total...")
    burned = client.get_burned_alpha_total()
    if burned:
        save_raw_response(conn, "taostats", "burned_alpha/total", burned, snapshot_ts)
        log(f"  -> Burned alpha data saved")
    else:
        log("  No burned alpha data")

    # ── Step g: Collect validators for TOP subnets ────────────────────────
    log(f"Step 7/7: Collecting validators for top {TOP_SUBNETS_DETAILED} subnets...")
    if subnets:
        selected = get_rotation_group(conn, subnets)
        total_validators = 0
        for i, s in enumerate(selected):
            netuid = s.get("netuid")
            name = s.get("name", f"Subnet {netuid}")
            if isinstance(name, dict):
                name = f"Subnet {netuid}"
            log(f"  [{i+1}/{len(selected)}] Subnet {netuid} ({name})...")
            validators = client.get_validators(netuid)
            if validators:
                n = insert_validators(conn, validators, netuid, snapshot_ts)
                total_validators += n
                log(f"    -> {n} validators")
            else:
                log(f"    -> No validator data")
            conn.sync()

        log(f"  Total: {total_validators} validators across {len(selected)} subnets")

    conn.sync()

    # ── Summary ───────────────────────────────────────────────────────────
    print("\n" + "=" * 70)
    print("COLLECTION SUMMARY")
    print("=" * 70)
    print(f"  Snapshot timestamp: {snapshot_ts} ({datetime.fromtimestamp(snapshot_ts, tz=timezone.utc).isoformat()})")
    print(f"  Total API requests: {client._total_requests}")
    print(f"  Runtime: ~{client._total_requests * 15}s estimated")
    if subnets:
        print(f"  Subnets collected: {len(subnets)}")
    if flows:
        print(f"  TAO flow entries: {len(flows)}")
    if tao_price:
        print(f"  TAO price: ${tao_price:.2f}")
    if errors:
        print(f"\n  ERRORS ({len(errors)}):")
        for e in errors:
            print(f"    - {e}")
    else:
        print(f"  Errors: NONE")
    print("=" * 70 + "\n")

    conn.close()
    log("Phase 5 complete.")


if __name__ == "__main__":
    main()
