# Bittensor Edge Discovery

Data pipeline + trading dashboard for discovering alpha in the Bittensor network.

## Architecture

```
pipeline/    → Python data collection + analysis (Hetzner VPS)
dashboard/   → Next.js app (Vercel)
```

Data flow: **Hetzner VPS** runs scripts → writes to **Turso DB** ← **Vercel Dashboard** reads

## Pipeline Scripts

| Script | Purpose |
|--------|---------|
| `0_setup.py` | Create DB schema, verify API connectivity |
| `1_collect_prices.py` | 30d TAO/USD from CoinGecko |
| `2_collect_onchain.py` | Subscan events + RPC subnets + TaoStats |
| `3_explore.py` | 5 statistical analyses → edge report |
| `4_backtest.py` | Generic backtesting engine |

## Quick Start

```bash
cd pipeline
pip install -r requirements.txt
python3 scripts/0_setup.py
python3 scripts/1_collect_prices.py
python3 scripts/2_collect_onchain.py
python3 scripts/3_explore.py
python3 scripts/4_backtest.py
```
