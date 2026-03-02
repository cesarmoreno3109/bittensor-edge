#!/usr/bin/env python3
"""Phase 3: Exploratory analysis — discover edges in collected data."""

import sys, os, json, warnings
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
warnings.filterwarnings("ignore")

import numpy as np
import pandas as pd
from scipy import stats
from datetime import datetime, timezone
from db import get_connection


def log(msg: str):
    print(f"[{datetime.now(timezone.utc).strftime('%H:%M:%S')}] {msg}")


def load_prices(conn):
    df = pd.read_sql("SELECT * FROM tao_prices ORDER BY timestamp", conn)
    if df.empty: return df
    df["datetime"] = pd.to_datetime(df["timestamp"], unit="s", utc=True)
    df = df.set_index("datetime").sort_index()
    return df[~df.index.duplicated(keep="last")]


def load_staking(conn):
    df = pd.read_sql("SELECT * FROM staking_events ORDER BY timestamp", conn)
    if df.empty: return df
    df["datetime"] = pd.to_datetime(df["timestamp"], unit="s", utc=True)
    return df


def load_subnets(conn):
    return pd.read_sql("SELECT * FROM subnet_info ORDER BY snapshot_ts, subnet_id", conn)


# ── Hurst exponent ────────────────────────────────────────────────────────────

def hurst_rs(ts):
    n = len(ts)
    if n < 20: return 0.5
    sizes, rs = [], []
    for s in range(10, min(n // 2, 100) + 1, max(1, min(n // 2, 100) // 20)):
        nc = n // s
        if nc < 1: continue
        rsl = []
        for i in range(nc):
            c = ts[i*s:(i+1)*s]
            m = np.mean(c)
            d = np.cumsum(c - m)
            r = np.max(d) - np.min(d)
            sd = np.std(c, ddof=1)
            if sd > 0: rsl.append(r / sd)
        if rsl:
            sizes.append(s)
            rs.append(np.mean(rsl))
    if len(sizes) < 3: return 0.5
    slope, *_ = stats.linregress(np.log(sizes), np.log(rs))
    return slope


# ── Analysis 1: Price Microstructure ──────────────────────────────────────────

def analyze_microstructure(prices):
    r = {"name": "PRICE MICROSTRUCTURE", "metrics": {}, "edge": "NONE", "reasoning": ""}
    if len(prices) < 20:
        r["reasoning"] = "Insufficient data"; return r

    hourly = prices["close"].resample("1h").last().dropna()
    if len(hourly) < 10:
        r["reasoning"] = "Insufficient hourly data"; return r

    rets = hourly.pct_change().dropna()

    # Returns at multiple frequencies
    for label, p in [("1h", 1), ("4h", 4), ("1d", 24)]:
        if len(hourly) >= p + 5:
            ret = hourly.pct_change(p).dropna()
            r["metrics"][f"mean_ret_{label}"] = round(float(ret.mean()), 6)
            r["metrics"][f"std_ret_{label}"] = round(float(ret.std()), 6)

    # Rolling 24h vol
    if len(rets) >= 24:
        vol = rets.rolling(24).std().dropna()
        r["metrics"]["avg_vol_24h"] = round(float(vol.mean()), 6)

    # Autocorrelations lags 1-12
    n = len(rets)
    threshold = 2.0 / np.sqrt(n)
    acf = {}
    sig = {}
    for lag in range(1, min(13, n)):
        ac = rets.autocorr(lag=lag)
        if not np.isnan(ac):
            acf[f"lag_{lag}"] = round(ac, 4)
            if abs(ac) > threshold:
                sig[f"lag_{lag}"] = round(ac, 4)
    r["metrics"]["autocorrelations"] = acf
    r["metrics"]["significant_acf"] = sig

    # Hurst
    h = hurst_rs(rets.values)
    r["metrics"]["hurst"] = round(h, 4)
    r["metrics"]["hurst_interp"] = "Mean-reverting" if h < 0.4 else "Trending" if h > 0.6 else "Random walk"

    # Volume-price corr
    if "volume" in prices.columns and prices["volume"].notna().sum() > 20:
        hvol = prices["volume"].resample("1h").sum().dropna()
        al = pd.concat([rets, hvol], axis=1, join="inner").dropna()
        if len(al) > 10:
            c, p = stats.pearsonr(al.iloc[:, 0].abs(), al.iloc[:, 1])
            r["metrics"]["vol_price_corr"] = round(c, 4)
            r["metrics"]["vol_price_pval"] = round(p, 4)

    if sig:
        r["edge"] = "MEDIUM"
        r["reasoning"] = f"Significant ACF at {list(sig.keys())}"
    elif abs(h - 0.5) > 0.1:
        r["edge"] = "LOW"
        r["reasoning"] = f"Hurst={h:.3f} suggests {'mean-reversion' if h < 0.5 else 'momentum'}"
    else:
        r["reasoning"] = "No significant autocorrelation detected"
    return r


# ── Analysis 2: On-chain → Price ─────────────────────────────────────────────

def analyze_onchain_price(prices, staking):
    r = {"name": "ON-CHAIN → PRICE", "metrics": {}, "edge": "NONE", "reasoning": ""}
    if staking.empty or len(prices) < 20:
        r["reasoning"] = "Insufficient data"; return r

    sc = staking.copy()
    sc["signed"] = sc.apply(
        lambda x: x["amount"] if x["event_type"] == "StakeAdded" and x["amount"]
        else -x["amount"] if x["event_type"] == "StakeRemoved" and x["amount"]
        else 0, axis=1
    )
    if sc["signed"].abs().sum() == 0:
        r["reasoning"] = "No staking amounts"; return r

    sc = sc.set_index("datetime")
    hflow = sc["signed"].resample("1h").sum().fillna(0)
    hclose = prices["close"].resample("1h").last().dropna()
    hrets = hclose.pct_change().dropna()

    al = pd.concat([hflow, hrets], axis=1, join="inner").dropna()
    al.columns = ["flow", "ret"]
    if len(al) < 20:
        r["reasoning"] = f"Only {len(al)} aligned obs"; return r

    best_c, best_lag, best_p = 0, 0, 1.0
    for lag in [0, 1, 4, 12, 24]:
        a = al["flow"].shift(lag) if lag else al["flow"]
        b = al["ret"]
        v = pd.concat([a, b], axis=1).dropna()
        if len(v) < 10: continue
        c, p = stats.pearsonr(v.iloc[:, 0], v.iloc[:, 1])
        r["metrics"][f"corr_lag{lag}h"] = round(c, 4)
        r["metrics"][f"pval_lag{lag}h"] = round(p, 4)
        if abs(c) > abs(best_c):
            best_c, best_lag, best_p = c, lag, p

    r["metrics"]["best_lag"] = best_lag
    r["metrics"]["best_corr"] = round(best_c, 4)
    r["metrics"]["best_pval"] = round(best_p, 4)

    if best_p < 0.05 and abs(best_c) > 0.15:
        r["edge"] = "HIGH"
        r["reasoning"] = f"Sig corr at lag {best_lag}h (r={best_c:.3f}, p={best_p:.4f})"
    elif best_p < 0.10:
        r["edge"] = "MEDIUM"
        r["reasoning"] = f"Marginal corr at lag {best_lag}h (r={best_c:.3f}, p={best_p:.4f})"
    else:
        r["reasoning"] = "No sig stake flow → price relationship"
    return r


# ── Analysis 3: Subnet Dynamics ───────────────────────────────────────────────

def analyze_subnets(subnets):
    r = {"name": "SUBNET DYNAMICS", "metrics": {}, "edge": "NONE", "reasoning": ""}
    if subnets.empty:
        r["reasoning"] = "No subnet data"; return r

    latest = subnets[subnets["snapshot_ts"] == subnets["snapshot_ts"].max()]

    if "emission_rate" in latest.columns and latest["emission_rate"].notna().any():
        em = latest["emission_rate"].dropna()
        tot = em.sum()
        if tot > 0:
            shares = em / tot
            r["metrics"]["emission_hhi"] = round(float((shares**2).sum()), 4)
            r["metrics"]["top3_share"] = round(float(shares.nlargest(3).sum()), 4)
            r["metrics"]["num_subnets"] = len(em)

    if "validator_count" in latest.columns and latest["validator_count"].notna().any():
        vc = latest["validator_count"].dropna()
        r["metrics"]["total_validators"] = int(vc.sum())
        r["metrics"]["avg_per_subnet"] = round(float(vc.mean()), 1)

    if "total_stake" in latest.columns and latest["total_stake"].notna().any():
        st = latest["total_stake"].dropna()
        r["metrics"]["total_stake"] = round(float(st.sum()), 2)

    r["reasoning"] = f"Snapshot of {len(latest)} subnets"
    return r


# ── Analysis 4: Volatility Structure ─────────────────────────────────────────

def analyze_volatility(prices):
    r = {"name": "VOLATILITY STRUCTURE", "metrics": {}, "edge": "NONE", "reasoning": ""}
    hourly = prices["close"].resample("1h").last().dropna()
    if len(hourly) < 48:
        r["reasoning"] = "Insufficient data"; return r

    rets = hourly.pct_change().dropna()
    absr = rets.abs()

    # |returns| ACF
    vacf = {}
    for lag in [1, 2, 4, 8, 12, 24]:
        if lag < len(absr):
            ac = absr.autocorr(lag=lag)
            if not np.isnan(ac):
                vacf[f"lag_{lag}h"] = round(ac, 4)
    r["metrics"]["vol_acf"] = vacf

    # Vol persistence
    if len(absr) >= 48:
        vp = absr.shift(1).dropna()
        vf = absr.loc[vp.index]
        v = pd.concat([vp, vf], axis=1).dropna()
        if len(v) > 20:
            c, p = stats.pearsonr(v.iloc[:, 0], v.iloc[:, 1])
            r["metrics"]["vol_persist_corr"] = round(c, 4)
            r["metrics"]["vol_persist_pval"] = round(p, 4)

    # Time-of-day
    if len(rets) >= 72:
        hv = absr.groupby(absr.index.hour).mean()
        ratio = hv.max() / hv.min() if hv.min() > 0 else 0
        r["metrics"]["intraday_vol_ratio"] = round(float(ratio), 2)

    lag1 = vacf.get("lag_1h", 0)
    if abs(lag1) > 0.2:
        r["edge"] = "MEDIUM"
        r["reasoning"] = f"Strong vol clustering (lag-1 ACF={lag1:.3f})"
    elif abs(lag1) > 0.1:
        r["edge"] = "LOW"
        r["reasoning"] = f"Moderate vol clustering (lag-1 ACF={lag1:.3f})"
    else:
        r["reasoning"] = "Weak vol clustering"
    return r


# ── Analysis 5: Distributions ────────────────────────────────────────────────

def analyze_distribution(prices):
    r = {"name": "DISTRIBUTIONS", "metrics": {}, "edge": "NONE", "reasoning": ""}
    hourly = prices["close"].resample("1h").last().dropna()
    if len(hourly) < 30:
        r["reasoning"] = "Insufficient data"; return r

    rets = hourly.pct_change().dropna()
    r["metrics"]["skewness"] = round(float(stats.skew(rets)), 4)
    r["metrics"]["kurtosis"] = round(float(stats.kurtosis(rets)), 4)

    jb, jp = stats.jarque_bera(rets)
    r["metrics"]["jarque_bera"] = round(float(jb), 4)
    r["metrics"]["jb_pval"] = round(float(jp), 6)

    n = len(rets)
    emp2s = (rets.abs() > 2 * rets.std()).sum() / n
    r["metrics"]["pct_beyond_2sigma"] = round(float(emp2s), 4)
    r["metrics"]["fat_tail_ratio"] = round(emp2s / 0.0455, 2)

    emp3s = (rets.abs() > 3 * rets.std()).sum()
    r["metrics"]["events_beyond_3sigma"] = int(emp3s)

    k = float(stats.kurtosis(rets))
    if k > 5:
        r["edge"] = "MEDIUM"
        r["reasoning"] = f"Heavy tails (kurtosis={k:.1f})"
    elif jp < 0.01:
        r["edge"] = "LOW"
        r["reasoning"] = f"Non-normal (JB p={jp:.4f})"
    else:
        r["reasoning"] = "Close to normal"
    return r


# ── Report ────────────────────────────────────────────────────────────────────

def report(analyses, prices, staking):
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    n_p = len(prices)
    n_e = len(staking)
    min_d = prices.index.min().strftime("%Y-%m-%d") if n_p else "N/A"
    max_d = prices.index.max().strftime("%Y-%m-%d") if n_p else "N/A"

    print("\n" + "=" * 65)
    print(f"BITTENSOR EDGE REPORT — {today}")
    print(f"Data: {min_d} to {max_d} | {n_p} prices | {n_e} events")
    print("=" * 65)

    hyps = []
    for a in analyses:
        print(f"\n--- {a['name']} ---")
        for k, v in a["metrics"].items():
            if isinstance(v, dict):
                print(f"  {k}:")
                for k2, v2 in list(v.items())[:8]:
                    print(f"    {k2}: {v2}")
            else:
                print(f"  {k}: {v}")
        print(f"  EDGE: {a['edge']}  |  {a['reasoning']}")
        if a["edge"] in ("HIGH", "MEDIUM"):
            hyps.append(a)

    rank = {"HIGH": 3, "MEDIUM": 2, "LOW": 1, "NONE": 0}
    hyps.sort(key=lambda x: rank.get(x["edge"], 0), reverse=True)

    print("\n" + "-" * 65)
    print("TOP HYPOTHESES:")
    if not hyps:
        print("  No significant edges found. Collect more data.")
    for i, h in enumerate(hyps[:3], 1):
        print(f"  {i}. [{h['edge']}] {h['name']} — {h['reasoning']}")

    print("\nNEXT STEP:")
    if hyps:
        print(f"  → Backtest strategy based on {hyps[0]['name']}")
    else:
        print("  → Collect more data (run daily for 1 week)")
    print("=" * 65)

    return {
        "date": today, "data_range": f"{min_d} to {max_d}",
        "n_prices": n_p, "n_events": n_e,
        "analyses": analyses,
        "hypotheses": [{"name": h["name"], "edge": h["edge"], "reasoning": h["reasoning"]} for h in hyps],
    }


def main():
    print("\n" + "=" * 65)
    print("BITTENSOR EDGE — PHASE 3: EXPLORE")
    print("=" * 65 + "\n")

    conn = get_connection()
    prices = load_prices(conn)
    staking = load_staking(conn)
    subnets = load_subnets(conn)
    log(f"Loaded: {len(prices)} prices, {len(staking)} events, {len(subnets)} subnets")

    if prices.empty:
        log("No price data. Run 1_collect_prices.py first.")
        conn.close(); return

    analyses = [
        analyze_microstructure(prices),
        analyze_onchain_price(prices, staking),
        analyze_subnets(subnets),
        analyze_volatility(prices),
        analyze_distribution(prices),
    ]

    rpt = report(analyses, prices, staking)

    conn.execute(
        "INSERT OR REPLACE INTO analysis_reports (timestamp, report_json) VALUES (?, ?)",
        (int(datetime.now(timezone.utc).timestamp()), json.dumps(rpt, default=str)),
    )
    conn.commit()
    conn.sync()
    conn.close()
    log("Phase 3 complete.")


if __name__ == "__main__":
    main()
