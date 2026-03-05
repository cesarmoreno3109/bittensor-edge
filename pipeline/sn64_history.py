"""Historical data tracking for SN64 signal bot.

Handles DB reads/writes for sn64_monitor, sn64_positions, sn64_portfolio.
"""

import time
import json
from datetime import datetime, timezone
from sn64_config import (
    RAO_TO_TAO,
    DCA_TRANCHE_USD,
    DCA_MAX_BUDGET_USD,
    DCA_MAX_TRANCHES,
    DCA_MIN_SCORE_FOR_BUY,
    DCA_COOLDOWN_HOURS,
)


# ── DB Schema ─────────────────────────────────────────────────────────────────

SCHEMA_SQL = [
    """CREATE TABLE IF NOT EXISTS sn64_monitor (
        timestamp INTEGER PRIMARY KEY,
        emission_pct REAL,
        ema_tao_flow REAL,
        net_flow_1d REAL,
        net_flow_7d REAL,
        net_flow_30d REAL,
        active_validators INTEGER,
        active_miners INTEGER,
        alpha_price_tao REAL,
        tao_price_usd REAL,
        top_validator_stake REAL,
        validator_hhi REAL,
        flow_rank INTEGER,
        signal_score REAL,
        signal_type TEXT
    )""",
    """CREATE TABLE IF NOT EXISTS sn64_positions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        timestamp INTEGER,
        action TEXT,
        amount_usd REAL,
        amount_tao REAL,
        alpha_price_tao REAL,
        tao_price_usd REAL,
        signal_score INTEGER,
        notes TEXT
    )""",
    """CREATE TABLE IF NOT EXISTS sn64_portfolio (
        id INTEGER PRIMARY KEY DEFAULT 1,
        total_invested_usd REAL DEFAULT 0,
        total_alpha_tokens REAL DEFAULT 0,
        avg_entry_price_tao REAL DEFAULT 0,
        current_pnl_pct REAL DEFAULT 0,
        last_updated INTEGER
    )""",
    """CREATE TABLE IF NOT EXISTS sn64_signal_state (
        id INTEGER PRIMARY KEY DEFAULT 1,
        current_signal TEXT DEFAULT 'WAIT',
        signal_since INTEGER DEFAULT 0,
        display_score REAL DEFAULT 50,
        last_raw_score REAL DEFAULT 50
    )""",
]


def create_tables(conn):
    """Create SN64 monitoring tables if they don't exist."""
    for sql in SCHEMA_SQL:
        conn.execute(sql)
    conn.commit()
    conn.sync()


# ── Monitor data ─────────────────────────────────────────────────────────────

def store_reading(conn, data: dict, signal_score: int, signal_type: str):
    """Store a monitoring data point."""
    ts = int(time.time())
    conn.execute(
        """INSERT OR REPLACE INTO sn64_monitor
           (timestamp, emission_pct, ema_tao_flow, net_flow_1d, net_flow_7d, net_flow_30d,
            active_validators, active_miners, alpha_price_tao, tao_price_usd,
            top_validator_stake, validator_hhi, flow_rank, signal_score, signal_type)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (
            ts,
            data.get("emission_pct", 0),
            data.get("ema_tao_flow", 0),
            data.get("net_flow_1d", 0),
            data.get("net_flow_7d", 0),
            data.get("net_flow_30d", 0),
            data.get("active_validators", 0),
            data.get("active_miners", 0),
            data.get("alpha_price_tao", 0),
            data.get("tao_price_usd", 0),
            data.get("top_validator_stake", 0),
            data.get("validator_hhi", 0),
            data.get("flow_rank", 0),
            signal_score,
            signal_type,
        ),
    )
    conn.commit()
    conn.sync()


def get_history(conn, limit: int = 700) -> list[dict]:
    """Get recent monitor readings, newest first."""
    res = conn.execute(
        """SELECT timestamp, emission_pct, ema_tao_flow, net_flow_1d, net_flow_7d, net_flow_30d,
                  active_validators, active_miners, alpha_price_tao, tao_price_usd,
                  top_validator_stake, validator_hhi, flow_rank, signal_score, signal_type
           FROM sn64_monitor
           ORDER BY timestamp DESC
           LIMIT ?""",
        (limit,),
    )
    cols = [
        "timestamp", "emission_pct", "ema_tao_flow", "net_flow_1d", "net_flow_7d", "net_flow_30d",
        "active_validators", "active_miners", "alpha_price_tao", "tao_price_usd",
        "top_validator_stake", "validator_hhi", "flow_rank", "signal_score", "signal_type",
    ]
    return [dict(zip(cols, row)) for row in res.fetchall()]


def get_previous_reading(conn) -> dict | None:
    """Get the most recent stored reading."""
    res = conn.execute(
        """SELECT timestamp, emission_pct, ema_tao_flow, net_flow_1d, net_flow_7d, net_flow_30d,
                  active_validators, active_miners, alpha_price_tao, tao_price_usd,
                  top_validator_stake, validator_hhi, flow_rank, signal_score, signal_type
           FROM sn64_monitor
           ORDER BY timestamp DESC
           LIMIT 1"""
    )
    cols = [
        "timestamp", "emission_pct", "ema_tao_flow", "net_flow_1d", "net_flow_7d", "net_flow_30d",
        "active_validators", "active_miners", "alpha_price_tao", "tao_price_usd",
        "top_validator_stake", "validator_hhi", "flow_rank", "signal_score", "signal_type",
    ]
    row = res.fetchone()
    if row:
        return dict(zip(cols, row))
    return None


def get_daily_scores(conn, hours: int = 24) -> list[int]:
    """Get signal scores over the last N hours."""
    cutoff = int(time.time()) - (hours * 3600)
    res = conn.execute(
        "SELECT signal_score FROM sn64_monitor WHERE timestamp > ? ORDER BY timestamp",
        (cutoff,),
    )
    return [int(row[0]) for row in res.fetchall()]


# ── Portfolio tracking ────────────────────────────────────────────────────────

def get_portfolio(conn) -> dict:
    """Get current portfolio state."""
    res = conn.execute("SELECT * FROM sn64_portfolio WHERE id = 1")
    row = res.fetchone()
    if row:
        return {
            "total_invested_usd": float(row[1] or 0),
            "total_alpha_tokens": float(row[2] or 0),
            "avg_entry_price_tao": float(row[3] or 0),
            "current_pnl_pct": float(row[4] or 0),
            "last_updated": int(row[5] or 0),
        }
    return {
        "total_invested_usd": 0,
        "total_alpha_tokens": 0,
        "avg_entry_price_tao": 0,
        "current_pnl_pct": 0,
        "last_updated": 0,
    }


def get_position_count(conn) -> int:
    """Get number of buy positions."""
    res = conn.execute("SELECT COUNT(*) FROM sn64_positions WHERE action = 'BUY'")
    row = res.fetchone()
    return int(row[0]) if row else 0


def get_last_buy_timestamp(conn) -> int:
    """Get timestamp of most recent paper buy."""
    res = conn.execute(
        "SELECT MAX(timestamp) FROM sn64_positions WHERE action = 'BUY'"
    )
    row = res.fetchone()
    return int(row[0]) if row and row[0] else 0


def execute_paper_buy(conn, alpha_price_tao: float, tao_price_usd: float,
                      signal_score: int) -> dict | None:
    """Execute a paper DCA buy if conditions are met.

    Returns buy details dict if executed, None if skipped.
    """
    portfolio = get_portfolio(conn)
    n_positions = get_position_count(conn)
    last_buy_ts = get_last_buy_timestamp(conn)
    now = int(time.time())

    # Check conditions
    if signal_score < DCA_MIN_SCORE_FOR_BUY:
        return None
    if n_positions >= DCA_MAX_TRANCHES:
        return None
    if portfolio["total_invested_usd"] >= DCA_MAX_BUDGET_USD:
        return None
    if last_buy_ts > 0 and (now - last_buy_ts) < DCA_COOLDOWN_HOURS * 3600:
        return None
    if alpha_price_tao <= 0 or tao_price_usd <= 0:
        return None

    # Calculate amounts
    amount_tao = DCA_TRANCHE_USD / tao_price_usd
    alpha_tokens = amount_tao / alpha_price_tao

    # Record position
    conn.execute(
        """INSERT INTO sn64_positions
           (timestamp, action, amount_usd, amount_tao, alpha_price_tao, tao_price_usd, signal_score, notes)
           VALUES (?,?,?,?,?,?,?,?)""",
        (now, "BUY", DCA_TRANCHE_USD, amount_tao, alpha_price_tao, tao_price_usd,
         signal_score, f"DCA tranche {n_positions + 1}/{DCA_MAX_TRANCHES}"),
    )

    # Update portfolio
    new_invested = portfolio["total_invested_usd"] + DCA_TRANCHE_USD
    new_tokens = portfolio["total_alpha_tokens"] + alpha_tokens
    new_avg = (portfolio["avg_entry_price_tao"] * portfolio["total_alpha_tokens"]
               + alpha_price_tao * alpha_tokens) / new_tokens if new_tokens > 0 else alpha_price_tao

    conn.execute(
        """INSERT OR REPLACE INTO sn64_portfolio
           (id, total_invested_usd, total_alpha_tokens, avg_entry_price_tao, current_pnl_pct, last_updated)
           VALUES (1,?,?,?,?,?)""",
        (new_invested, new_tokens, new_avg, 0, now),
    )
    conn.commit()
    conn.sync()

    return {
        "tranche": n_positions + 1,
        "amount_usd": DCA_TRANCHE_USD,
        "amount_tao": amount_tao,
        "alpha_tokens": alpha_tokens,
        "alpha_price_tao": alpha_price_tao,
        "tao_price_usd": tao_price_usd,
        "total_invested": new_invested,
    }


def update_portfolio_pnl(conn, current_alpha_price: float):
    """Update portfolio P&L based on current alpha price."""
    portfolio = get_portfolio(conn)
    if portfolio["total_alpha_tokens"] <= 0 or portfolio["avg_entry_price_tao"] <= 0:
        return

    pnl_pct = ((current_alpha_price - portfolio["avg_entry_price_tao"])
               / portfolio["avg_entry_price_tao"]) * 100

    conn.execute(
        """UPDATE sn64_portfolio
           SET current_pnl_pct = ?, last_updated = ?
           WHERE id = 1""",
        (pnl_pct, int(time.time())),
    )
    conn.commit()
    conn.sync()
