#!/usr/bin/env python3
"""Phase 2: Collect on-chain data — Subscan events, RPC, TaoStats."""

import sys
import os
import time
import json
import requests

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from datetime import datetime, timezone
from config import (
    SUBSCAN_BASE, SUBSCAN_RATE_LIMIT_SECONDS,
    RPC_ENDPOINT, TAOSTATS_BASE, MAX_EVENTS, MAX_SUBNETS,
)
from db import get_connection


def log(msg: str):
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    print(f"[{ts}] {msg}")


def store_raw(conn, source, endpoint, data):
    conn.execute(
        "INSERT INTO raw_responses (source, endpoint, timestamp, response_json) VALUES (?, ?, ?, ?)",
        (source, endpoint, int(time.time()), json.dumps(data, default=str)[:50000]),
    )


# ── Subscan Events ───────────────────────────────────────────────────────────

def collect_subscan_events(conn):
    event_types = ["StakeAdded", "StakeRemoved", "NeuronRegistered", "WeightsSet"]
    total = 0

    for event_name in event_types:
        log(f"Subscan: {event_name}...")
        page = 0
        count = 0

        while count < MAX_EVENTS:
            time.sleep(SUBSCAN_RATE_LIMIT_SECONDS)
            try:
                resp = requests.post(
                    f"{SUBSCAN_BASE}/scan/events",
                    json={"module": "subtensormodule", "event_name": event_name, "page": page, "row": 20},
                    timeout=20,
                )
                resp.raise_for_status()
                data = resp.json()

                if page == 0:
                    store_raw(conn, "subscan", f"events/{event_name}", data)

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
                    except: pass

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

        log(f"  {event_name}: {count} events")
        total += count

    conn.sync()
    return total


# ── RPC Subnet State ─────────────────────────────────────────────────────────

def collect_rpc(conn):
    log("RPC: Fetching subnet state...")
    snapshot_ts = int(time.time())
    collected = 0

    for sid in range(1, MAX_SUBNETS + 1):
        try:
            resp = requests.post(
                RPC_ENDPOINT,
                json={"method": "subtensorModule_getSubnetInfo", "params": [sid], "id": 1, "jsonrpc": "2.0"},
                timeout=10,
            )
            data = resp.json()
            if sid == 1:
                store_raw(conn, "rpc", "getSubnetInfo/1", data)

            result = data.get("result")
            if result is None:
                continue

            emission = None
            val_count = None
            total_stake = None
            if isinstance(result, dict):
                emission = result.get("emission_value", result.get("emission"))
                if emission is not None:
                    try: emission = float(emission) / 1e9
                    except: emission = None
                val_count = result.get("validator_count", result.get("num_validators"))
                total_stake = result.get("total_stake")
                if total_stake is not None:
                    try: total_stake = float(total_stake) / 1e9
                    except: total_stake = None

            conn.execute(
                "INSERT OR REPLACE INTO subnet_info (snapshot_ts, subnet_id, emission_rate, validator_count, total_stake) VALUES (?, ?, ?, ?, ?)",
                (snapshot_ts, sid, emission, val_count, total_stake),
            )
            collected += 1
            time.sleep(0.1)
        except Exception as e:
            if sid <= 3:
                log(f"  RPC error subnet {sid}: {e}")

    conn.commit()
    conn.sync()
    log(f"  RPC: {collected} subnets")
    return collected


# ── TaoStats ──────────────────────────────────────────────────────────────────

def collect_taostats(conn):
    log("TaoStats: Fetching data...")
    snapshot_ts = int(time.time())
    s_count = 0
    v_count = 0

    # Subnets
    try:
        resp = requests.get(f"{TAOSTATS_BASE}/subnet/latest", timeout=15)
        resp.raise_for_status()
        data = resp.json()
        store_raw(conn, "taostats", "subnet/latest", data)

        subnets = data if isinstance(data, list) else data.get("data", data.get("subnets", []))
        if isinstance(subnets, list):
            for s in subnets:
                sid = s.get("netuid", s.get("subnet_id"))
                if sid is None:
                    continue
                emission = s.get("emission", s.get("emission_rate"))
                if emission is not None:
                    try: emission = float(emission)
                    except: emission = None
                vc = s.get("validator_count", s.get("num_validators"))
                stake = s.get("total_stake")
                if stake is not None:
                    try: stake = float(stake)
                    except: stake = None

                conn.execute(
                    "INSERT OR REPLACE INTO subnet_info (snapshot_ts, subnet_id, emission_rate, validator_count, total_stake) VALUES (?, ?, ?, ?, ?)",
                    (snapshot_ts, int(sid), emission, vc, stake),
                )
                s_count += 1
            conn.commit()
        log(f"  Subnets: {s_count}")
    except Exception as e:
        log(f"  Subnet error: {e}")

    time.sleep(1)

    # Validators
    try:
        resp = requests.get(f"{TAOSTATS_BASE}/validator/latest", timeout=15)
        resp.raise_for_status()
        data = resp.json()
        store_raw(conn, "taostats", "validator/latest", data)

        validators = data if isinstance(data, list) else data.get("data", data.get("validators", []))
        if isinstance(validators, list):
            for v in validators:
                hotkey = v.get("hotkey", v.get("address", ""))
                sid = v.get("netuid", v.get("subnet_id", 0))
                weight = v.get("stake", v.get("weight", 0))
                try: weight = float(weight)
                except: weight = 0.0

                conn.execute(
                    "INSERT OR REPLACE INTO validator_weights (snapshot_ts, validator_hotkey, subnet_id, weight) VALUES (?, ?, ?, ?)",
                    (snapshot_ts, str(hotkey), int(sid), weight),
                )
                v_count += 1
            conn.commit()
        log(f"  Validators: {v_count}")
    except Exception as e:
        log(f"  Validator error: {e}")

    conn.sync()
    return s_count + v_count


def print_summary(conn):
    staking = conn.execute("SELECT COUNT(*) FROM staking_events").fetchone()[0]
    subnets = conn.execute("SELECT COUNT(*) FROM subnet_info").fetchone()[0]
    validators = conn.execute("SELECT COUNT(*) FROM validator_weights").fetchone()[0]
    events = conn.execute("SELECT event_type, COUNT(*) FROM staking_events GROUP BY event_type").fetchall()

    print(f"\n  Staking events: {staking}")
    for e, c in events:
        print(f"    {e}: {c}")
    print(f"  Subnet snapshots: {subnets}")
    print(f"  Validator records: {validators}\n")


def main():
    print("\n" + "=" * 55)
    print("BITTENSOR EDGE — PHASE 2: COLLECT ON-CHAIN DATA")
    print("=" * 55 + "\n")

    conn = get_connection()

    try: n1 = collect_subscan_events(conn)
    except Exception as e:
        log(f"Subscan failed: {e}"); n1 = 0

    try: n2 = collect_rpc(conn)
    except Exception as e:
        log(f"RPC failed: {e}"); n2 = 0

    try: n3 = collect_taostats(conn)
    except Exception as e:
        log(f"TaoStats failed: {e}"); n3 = 0

    print_summary(conn)
    conn.close()
    log(f"Phase 2 complete. Subscan={n1}, RPC={n2}, TaoStats={n3}")


if __name__ == "__main__":
    main()
