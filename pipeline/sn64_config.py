"""Configuration for SN64 Chutes signal bot."""

import os
from dotenv import load_dotenv

load_dotenv()

# ── Telegram ──────────────────────────────────────────────────────────────────
TELEGRAM_BOT_TOKEN = os.getenv("SN64_TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("SN64_TELEGRAM_CHAT_ID", "")

# ── TaoStats API ──────────────────────────────────────────────────────────────
TAOSTATS_BASE = "https://api.taostats.io"
TAOSTATS_API_KEY = os.getenv("TAOSTATS_API_KEY", "")
API_RATE_LIMIT_SECONDS = 15  # 4 req/min

# ── Target subnet ────────────────────────────────────────────────────────────
TARGET_NETUID = 64
TARGET_NAME = "Chutes"

# ── Timing ────────────────────────────────────────────────────────────────────
CYCLE_INTERVAL_SECONDS = 15 * 60        # 15 minutes
REPORT_INTERVAL_SECONDS = 6 * 60 * 60   # 6 hours
DAILY_SUMMARY_HOUR_UTC = 8              # 08:00 UTC

# ── Signal thresholds ────────────────────────────────────────────────────────
SCORE_THRESHOLDS = {
    "STRONG_BUY": 85,
    "BUY": 70,
    "ACCUMULATE": 55,
    "WAIT": 40,
    "CAUTION": 25,
    "EXIT": 0,
}

def score_to_signal(score: int) -> str:
    """Convert composite score to signal label."""
    if score >= 85:
        return "STRONG BUY"
    elif score >= 70:
        return "BUY"
    elif score >= 55:
        return "ACCUMULATE"
    elif score >= 40:
        return "WAIT"
    elif score >= 25:
        return "CAUTION"
    else:
        return "EXIT"

# ── DCA strategy ──────────────────────────────────────────────────────────────
DCA_TRANCHE_USD = 100.0
DCA_MAX_BUDGET_USD = 1000.0
DCA_MAX_TRANCHES = 10
DCA_MIN_SCORE_FOR_BUY = 70
DCA_COOLDOWN_HOURS = 24  # Min hours between paper buys

# ── Indicator weights ────────────────────────────────────────────────────────
WEIGHTS = {
    "emission_trend": 25,
    "flow_momentum": 25,
    "flow_magnitude": 15,
    "miner_health": 10,
    "validator_concentration": 10,
    "relative_dominance": 10,
    "alpha_price_trend": 5,
}

# ── Anomaly thresholds ───────────────────────────────────────────────────────
ANOMALY_EMISSION_DROP_PCT = 2.0         # Alert if emission drops >2% in one reading
ANOMALY_MINER_DROP_COUNT = 5            # Alert if miners drop >5 in one reading
ANOMALY_ALPHA_PRICE_DROP_PCT = 5.0      # Alert if alpha price drops >5% in one reading
ANOMALY_FLOW_SPIKE_TAO = 500.0          # Alert if single-period flow spike >500 TAO

# ── RAO conversion ───────────────────────────────────────────────────────────
RAO_TO_TAO = 1e-9
