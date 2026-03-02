#!/usr/bin/env python3
"""Phase 1: Collect TAO/USD price data from CoinGecko."""

import sys
import os
import time
import json
import requests

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from datetime import datetime, timezone
from config import COINGECKO_BASE, COINGECKO_RATE_LIMIT_SECONDS, PRICE_DAYS
from db import get_connection


def log(msg: str):
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    print(f"[{ts}] {msg}")


def store_raw(conn, source, endpoint, data):
    conn.execute(
        "INSERT INTO raw_responses (source, endpoint, timestamp, response_json) VALUES (?, ?, ?, ?)",
        (source, endpoint, int(time.time()), json.dumps(data)[:50000]),
    )


def collect_market_chart(conn):
    log("Fetching CoinGecko market_chart...")
    url = f"{COINGECKO_BASE}/coins/bittensor/market_chart"
    params = {"vs_currency": "usd", "days": PRICE_DAYS}

    try:
        resp = requests.get(url, params=params, timeout=30)
        resp.raise_for_status()
        data = resp.json()
        store_raw(conn, "coingecko", "market_chart", data)
    except Exception as e:
        log(f"ERROR: {e}")
        return 0

    prices = data.get("prices", [])
    volumes = data.get("total_volumes", [])
    vol_map = {int(v[0]): v[1] for v in volumes}

    inserted = 0
    for ts_ms, price in prices:
        ts = int(ts_ms) // 1000
        vol = vol_map.get(int(ts_ms))
        try:
            conn.execute(
                "INSERT OR IGNORE INTO tao_prices (timestamp, open, high, low, close, volume, source) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (ts, price, price, price, price, vol, "coingecko_market_chart"),
            )
            inserted += 1
        except Exception:
            pass

    conn.commit()
    conn.sync()
    log(f"market_chart: {inserted} points from {len(prices)} raw.")
    return inserted


def collect_ohlc(conn):
    log(f"Sleeping {COINGECKO_RATE_LIMIT_SECONDS}s (rate limit)...")
    time.sleep(COINGECKO_RATE_LIMIT_SECONDS)

    log("Fetching CoinGecko OHLC...")
    url = f"{COINGECKO_BASE}/coins/bittensor/ohlc"
    params = {"vs_currency": "usd", "days": PRICE_DAYS}

    try:
        resp = requests.get(url, params=params, timeout=30)
        resp.raise_for_status()
        data = resp.json()
        store_raw(conn, "coingecko", "ohlc", data)
    except Exception as e:
        log(f"ERROR: {e}")
        return 0

    inserted = 0
    for candle in data:
        if len(candle) < 5:
            continue
        ts = int(candle[0]) // 1000
        try:
            conn.execute(
                "INSERT OR REPLACE INTO tao_prices (timestamp, open, high, low, close, volume, source) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (ts, candle[1], candle[2], candle[3], candle[4], None, "coingecko_ohlc"),
            )
            inserted += 1
        except Exception:
            pass

    conn.commit()
    conn.sync()
    log(f"OHLC: {inserted} candles from {len(data)} raw.")
    return inserted


def validate(conn):
    rows = conn.execute("SELECT timestamp, close FROM tao_prices ORDER BY timestamp").fetchall()
    if not rows:
        log("WARNING: No price data!")
        return

    min_d = datetime.fromtimestamp(rows[0][0], tz=timezone.utc).strftime("%Y-%m-%d")
    max_d = datetime.fromtimestamp(rows[-1][0], tz=timezone.utc).strftime("%Y-%m-%d")

    gaps = 0
    for i in range(1, len(rows)):
        if rows[i][0] - rows[i - 1][0] > 7200:
            gaps += 1

    print(f"\n  Total rows: {len(rows)}  |  Range: {min_d} to {max_d}  |  Gaps>2h: {gaps}\n")


def main():
    print("\n" + "=" * 55)
    print("BITTENSOR EDGE — PHASE 1: COLLECT PRICES")
    print("=" * 55 + "\n")

    conn = get_connection()

    last = conn.execute("SELECT MAX(timestamp) FROM tao_prices").fetchone()[0]
    if last:
        log(f"Existing data up to {datetime.fromtimestamp(last, tz=timezone.utc).strftime('%Y-%m-%d %H:%M')}")
    else:
        log("No existing data. Fresh collection.")

    n1 = collect_market_chart(conn)
    n2 = collect_ohlc(conn)

    log(f"Done: market_chart={n1}, OHLC={n2}")
    validate(conn)
    conn.close()


if __name__ == "__main__":
    main()
