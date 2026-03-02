#!/usr/bin/env python3
"""Phase 2: Collect on-chain data — RPC subnet/delegate info, Subscan (if available)."""

import sys
import os
import time
import json
import struct
import requests

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from datetime import datetime, timezone
from config import RPC_ENDPOINT, SUBSCAN_BASE, SUBSCAN_RATE_LIMIT_SECONDS, MAX_SUBNETS
from db import get_connection


def log(msg: str):
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    print(f"[{ts}] {msg}")


def store_raw(conn, source, endpoint, data):
    try:
        conn.execute(
            "INSERT INTO raw_responses (source, endpoint, timestamp, response_json) VALUES (?, ?, ?, ?)",
            (source, endpoint, int(time.time()), json.dumps(data, default=str)[:50000]),
        )
        conn.commit()
    except Exception:
        pass


# ── RPC: Subnet Hyperparameters ───────────────────────────────────────────────

def rpc_call(method, params=None):
    payload = {"method": method, "params": params or [], "id": 1, "jsonrpc": "2.0"}
    resp = requests.post(RPC_ENDPOINT, json=payload, timeout=15)
    return resp.json()


def collect_rpc_subnets(conn):
    """Get subnet hyperparams which return human-readable JSON."""
    log("RPC: Querying subnet hyperparams for subnets 1-52...")
    snapshot_ts = int(time.time())
    collected = 0

    for sid in range(1, MAX_SUBNETS + 1):
        try:
            data = rpc_call("subnetInfo_getSubnetHyperparams", [sid])

            if sid <= 3:
                store_raw(conn, "rpc", f"getSubnetHyperparams/{sid}", data)

            result = data.get("result")
            if result is None:
                continue

            # Hyperparams may be dict or SCALE bytes — try dict first
            if isinstance(result, dict):
                emission = result.get("tempo") or result.get("emission_value")
                max_validators = result.get("max_validators") or result.get("max_allowed_validators")
                min_stake = result.get("min_stake") or result.get("immunity_period")

                conn.execute(
                    "INSERT OR REPLACE INTO subnet_info (snapshot_ts, subnet_id, emission_rate, validator_count, total_stake) VALUES (?, ?, ?, ?, ?)",
                    (snapshot_ts, sid, emission, max_validators, min_stake),
                )
                collected += 1
            else:
                # SCALE encoded — store as raw, mark subnet as existing
                conn.execute(
                    "INSERT OR REPLACE INTO subnet_info (snapshot_ts, subnet_id, emission_rate, validator_count, total_stake) VALUES (?, ?, ?, ?, ?)",
                    (snapshot_ts, sid, None, None, None),
                )
                collected += 1

            time.sleep(0.05)
        except Exception as e:
            if sid <= 3:
                log(f"  Subnet {sid} error: {e}")

    conn.commit()
    conn.sync()
    log(f"  Subnets collected: {collected}")
    return collected


# ── RPC: Delegate info (validators) ──────────────────────────────────────────

def collect_rpc_delegates(conn):
    """Get delegate information (top validators)."""
    log("RPC: Querying delegates...")
    snapshot_ts = int(time.time())
    collected = 0

    try:
        data = rpc_call("delegateInfo_getDelegates")
        store_raw(conn, "rpc", "getDelegates", {"result_type": str(type(data.get("result")).__name__), "has_result": data.get("result") is not None})

        result = data.get("result")
        if result is None:
            log("  No delegate data returned")
            return 0

        # Result is SCALE-encoded byte array — store raw and note it
        if isinstance(result, list):
            # It's bytes as array — count non-zero entries as proxy
            log(f"  Delegate data received: {len(result)} bytes (SCALE-encoded)")
            # Store a synthetic record so we know data exists
            conn.execute(
                "INSERT OR REPLACE INTO raw_responses (source, endpoint, timestamp, response_json) VALUES (?, ?, ?, ?)",
                ("rpc", "getDelegates/binary", snapshot_ts, json.dumps({"bytes": len(result), "note": "SCALE-encoded delegate data"})),
            )
            conn.commit()
        elif isinstance(result, dict):
            # If it returns a dict (newer API), parse it
            for key, val in result.items():
                hotkey = str(key)[:48]
                stake = val.get("total_stake", 0) if isinstance(val, dict) else 0
                try:
                    stake = float(stake) / 1e9
                except:
                    stake = 0

                conn.execute(
                    "INSERT OR REPLACE INTO validator_weights (snapshot_ts, validator_hotkey, subnet_id, weight) VALUES (?, ?, ?, ?)",
                    (snapshot_ts, hotkey, 0, stake),
                )
                collected += 1
            conn.commit()

    except Exception as e:
        log(f"  Delegate error: {e}")

    conn.sync()
    log(f"  Validators collected: {collected}")
    return collected


# ── Subscan Events (best-effort) ─────────────────────────────────────────────

def collect_subscan_events(conn):
    """Try Subscan — may not be available for Bittensor."""
    log("Subscan: Testing availability...")

    # Quick probe
    try:
        resp = requests.post(
            f"{SUBSCAN_BASE}/scan/metadata",
            json={}, timeout=10,
            headers={"Content-Type": "application/json"},
        )
        if resp.status_code != 200:
            log(f"  Subscan not available (HTTP {resp.status_code}). Skipping.")
            return 0
    except Exception as e:
        log(f"  Subscan not reachable: {e}. Skipping.")
        return 0

    event_types = ["StakeAdded", "StakeRemoved", "NeuronRegistered", "WeightsSet"]
    total = 0

    for event_name in event_types:
        log(f"  Fetching {event_name}...")
        page = 0
        count = 0

        while count < 500:  # Limit per event type
            time.sleep(SUBSCAN_RATE_LIMIT_SECONDS)
            try:
                resp = requests.post(
                    f"{SUBSCAN_BASE}/scan/events",
                    json={"module": "subtensormodule", "event_name": event_name, "page": page, "row": 20},
                    timeout=20,
                )
                if resp.status_code != 200:
                    break

                data = resp.json()
                events = data.get("data", {}).get("events", [])
                if not events:
                    break

                for ev in events:
                    block_num = ev.get("block_num", 0)
                    ev_ts = ev.get("block_timestamp", 0)
                    params = ev.get("params", "[]")

                    amount, hotkey, subnet_id = None, "", None
                    try:
                        plist = json.loads(params) if isinstance(params, str) else params
                        for p in plist:
                            name = p.get("name", "").lower()
                            val = p.get("value", "")
                            if name in ("amount", "tao_amount", "alpha_amount"):
                                try: amount = float(val) / 1e9
                                except: pass
                            elif name in ("hotkey", "delegate"):
                                hotkey = str(val)
                            elif name in ("netuid", "subnet_id"):
                                try: subnet_id = int(val)
                                except: pass
                    except:
                        pass

                    conn.execute(
                        "INSERT OR IGNORE INTO staking_events (block_num, timestamp, event_type, subnet_id, amount, hotkey) VALUES (?, ?, ?, ?, ?, ?)",
                        (block_num, ev_ts, event_name, subnet_id, amount, hotkey),
                    )
                    count += 1

                conn.commit()
                page += 1
                if len(events) < 20:
                    break
            except Exception as e:
                log(f"  Error: {e}")
                break

        log(f"    {event_name}: {count}")
        total += count

    conn.sync()
    return total


# ── Summary ───────────────────────────────────────────────────────────────────

def print_summary(conn):
    try:
        conn.sync()
        staking = conn.execute("SELECT COUNT(*) FROM staking_events").fetchone()[0]
        subnets = conn.execute("SELECT COUNT(*) FROM subnet_info").fetchone()[0]
        validators = conn.execute("SELECT COUNT(*) FROM validator_weights").fetchone()[0]
        raw = conn.execute("SELECT COUNT(*) FROM raw_responses").fetchone()[0]

        print(f"\n  Staking events: {staking}")
        print(f"  Subnet snapshots: {subnets}")
        print(f"  Validator records: {validators}")
        print(f"  Raw responses stored: {raw}\n")
    except Exception as e:
        log(f"Summary error: {e}")


def main():
    print("\n" + "=" * 55)
    print("BITTENSOR EDGE — PHASE 2: COLLECT ON-CHAIN DATA")
    print("=" * 55 + "\n")

    conn = get_connection()

    try: n1 = collect_rpc_subnets(conn)
    except Exception as e:
        log(f"RPC subnets failed: {e}"); n1 = 0

    try: n2 = collect_rpc_delegates(conn)
    except Exception as e:
        log(f"RPC delegates failed: {e}"); n2 = 0

    try: n3 = collect_subscan_events(conn)
    except Exception as e:
        log(f"Subscan failed: {e}"); n3 = 0

    print_summary(conn)
    conn.close()
    log(f"Phase 2 complete. Subnets={n1}, Delegates={n2}, Subscan={n3}")


if __name__ == "__main__":
    main()
