"""Centralized configuration for Bittensor Edge Discovery pipeline."""

import os
from dotenv import load_dotenv

load_dotenv()

# --- Database ---
TURSO_DB_URL = os.getenv("TURSO_DB_URL", "file:bittensor_edge.db")
TURSO_AUTH_TOKEN = os.getenv("TURSO_AUTH_TOKEN", "")

# --- CoinGecko ---
COINGECKO_BASE = "https://api.coingecko.com/api/v3"
COINGECKO_RATE_LIMIT_SECONDS = 6  # Free tier: max 10 req/min

# --- Subscan ---
SUBSCAN_BASE = "https://bittensor.api.subscan.io/api"
SUBSCAN_RATE_LIMIT_SECONDS = 0.5  # 2 req/sec without API key

# --- Bittensor RPC ---
RPC_ENDPOINT = "https://entrypoint-finney.opentensor.ai"

# --- TaoStats ---
TAOSTATS_BASE = "https://api.taostats.io"
TAOSTATS_API_KEY = os.getenv("TAOSTATS_API_KEY", "")
TAOSTATS_RATE_LIMIT_SECONDS = 15  # 4 req/min (API limit is 5/min)

# --- Collection parameters ---
PRICE_DAYS = 30
MAX_EVENTS = 10000
MAX_SUBNETS = 52
TOP_SUBNETS_DETAILED = 10  # Subnets to get validator data per run
