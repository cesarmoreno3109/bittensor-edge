#!/usr/bin/env python3
"""SN64 Chutes Signal Bot — 24/7 monitoring with Telegram alerts.

Runs as a systemd service. Collects data every 15 minutes from TaoStats API,
calculates composite signal scores, and sends alerts via Telegram.
"""

import sys
import os
import time
import json
import requests
import traceback
from datetime import datetime, timezone
from collections import deque

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sn64_config import (
    TELEGRAM_BOT_TOKEN,
    TELEGRAM_CHAT_ID,
    TAOSTATS_BASE,
    TAOSTATS_API_KEY,
    API_RATE_LIMIT_SECONDS,
    TARGET_NETUID,
    TARGET_NAME,
    CYCLE_INTERVAL_SECONDS,
    REPORT_INTERVAL_SECONDS,
    DAILY_SUMMARY_HOUR_UTC,
    RAO_TO_TAO,
    score_to_signal,
)
from sn64_signals import calculate_signal, detect_anomalies, IndicatorResult
from sn64_history import (
    create_tables,
    store_reading,
    get_history,
    get_previous_reading,
    get_daily_scores,
    get_portfolio,
    get_position_count,
    execute_paper_buy,
    update_portfolio_pnl,
)


def log(msg: str):
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    print(f"[{ts}] {msg}", flush=True)


# ── Telegram messaging ───────────────────────────────────────────────────────

def send_telegram(text: str, retries: int = 3):
    """Send message via Telegram Bot API with retry."""
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        log("  WARNING: Telegram credentials not set, skipping message")
        return False

    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    }

    for attempt in range(retries):
        try:
            resp = requests.post(url, json=payload, timeout=15)
            if resp.status_code == 200:
                log("  Telegram message sent OK")
                return True
            else:
                log(f"  Telegram error {resp.status_code}: {resp.text[:100]}")
        except Exception as e:
            log(f"  Telegram send failed (attempt {attempt+1}): {e}")

        if attempt < retries - 1:
            time.sleep(5 * (attempt + 1))

    log("  FAILED to send Telegram message after all retries")
    return False


# ── TaoStats API calls ───────────────────────────────────────────────────────

_request_times: deque = deque(maxlen=4)


def _rate_limit():
    """Enforce rate limiting between API calls."""
    now = time.time()
    if _request_times:
        elapsed = now - _request_times[-1]
        if elapsed < API_RATE_LIMIT_SECONDS:
            wait = API_RATE_LIMIT_SECONDS - elapsed
            time.sleep(wait)
    _request_times.append(time.time())


def api_get(endpoint: str, params: dict = None) -> dict | None:
    """Make authenticated GET to TaoStats API."""
    _rate_limit()
    url = f"{TAOSTATS_BASE}/{endpoint}"
    headers = {"Authorization": TAOSTATS_API_KEY}
    try:
        resp = requests.get(url, headers=headers, params=params, timeout=30)
        if resp.status_code == 200:
            return resp.json()
        log(f"  API {resp.status_code} for {endpoint}")
        return None
    except Exception as e:
        log(f"  API error for {endpoint}: {e}")
        return None


def collect_data() -> dict | None:
    """Run one data collection cycle (4 API calls)."""
    data = {}

    # 1. Subnet info for SN64
    log("  [1/4] GET subnet/latest (SN64)...")
    subnet_resp = api_get("api/subnet/latest/v1")
    if subnet_resp and "data" in subnet_resp:
        sn64 = None
        all_subnets = subnet_resp["data"]
        emissions = []
        for s in all_subnets:
            em = float(s.get("projected_emission") or s.get("emission") or 0)
            emissions.append((s.get("netuid"), em))
            if s.get("netuid") == TARGET_NETUID:
                sn64 = s

        if sn64:
            data["emission_pct"] = float(sn64.get("projected_emission") or 0)
            data["ema_tao_flow"] = float(sn64.get("ema_tao_flow") or 0)
            data["net_flow_1d"] = float(sn64.get("net_flow_1_day") or 0)
            data["net_flow_7d"] = float(sn64.get("net_flow_7_days") or 0)
            data["net_flow_30d"] = float(sn64.get("net_flow_30_days") or 0)
            data["active_validators"] = int(sn64.get("active_validators") or 0)
            data["active_miners"] = int(sn64.get("active_miners") or 0)
            data["active_keys"] = int(sn64.get("active_keys") or 0)
            data["fee_rate"] = float(sn64.get("fee_rate") or 0)

            # Calculate flow rank (rank SN64 by 30d flow among all subnets)
            flows = [(s.get("netuid"), float(s.get("net_flow_30_days") or 0))
                     for s in all_subnets if s.get("netuid") != 0]
            flows.sort(key=lambda x: x[1], reverse=True)
            data["flow_rank"] = next((i + 1 for i, (nid, _) in enumerate(flows)
                                      if nid == TARGET_NETUID), 0)

            # Find #2 subnet by emission for dominance scoring
            emissions.sort(key=lambda x: x[1], reverse=True)
            sn64_em_rank = None
            second_emission = 0
            for i, (nid, em) in enumerate(emissions):
                if nid == TARGET_NETUID:
                    sn64_em_rank = i + 1
                elif nid != 0 and em > 0:
                    if sn64_em_rank is not None:
                        second_emission = em
                        break
                    elif i == 0:
                        # SN64 not #1 — find who is #1 and that's our comparison
                        pass

            # Get the highest non-SN64, non-root emission
            non_sn64_ems = [(nid, em) for nid, em in emissions
                            if nid != TARGET_NETUID and nid != 0]
            data["second_emission"] = non_sn64_ems[0][1] if non_sn64_ems else 0
        else:
            log(f"  WARNING: SN{TARGET_NETUID} not found in subnet data!")
            return None
    else:
        log("  ERROR: Failed to get subnet data")
        return None

    # 2. Validators for SN64
    log("  [2/4] GET validator/latest (SN64)...")
    val_resp = api_get("api/validator/latest/v1", params={"netuid": TARGET_NETUID})
    if val_resp and "data" in val_resp:
        validators = val_resp["data"]
        stakes = []
        for v in validators:
            stake = float(v.get("stake") or v.get("system_stake") or 0)
            stakes.append(stake)

        if stakes:
            total_stake = sum(stakes)
            if total_stake > 0:
                shares = [s / total_stake for s in stakes]
                data["validator_hhi"] = sum(s ** 2 for s in shares)
                data["top_validator_stake"] = max(stakes) * RAO_TO_TAO
            else:
                data["validator_hhi"] = 1.0
                data["top_validator_stake"] = 0
        else:
            data["validator_hhi"] = 0.5
            data["top_validator_stake"] = 0
    else:
        data["validator_hhi"] = 0.5
        data["top_validator_stake"] = 0

    # 3. Metagraph for alpha price derivation
    log("  [3/4] GET metagraph/latest (SN64)...")
    meta_resp = api_get("api/metagraph/latest/v1", params={"netuid": TARGET_NETUID})
    alpha_price_tao = 0
    if meta_resp and "data" in meta_resp:
        neurons = meta_resp["data"]
        # Derive alpha price from daily validation rewards ratio
        total_alpha_rewards = 0
        total_tao_equiv = 0
        for n in neurons:
            a = float(n.get("daily_validating_alpha") or 0)
            t = float(n.get("daily_validating_alpha_as_tao") or 0)
            total_alpha_rewards += a
            total_tao_equiv += t
        if total_alpha_rewards > 0 and total_tao_equiv > 0:
            alpha_price_tao = total_tao_equiv / total_alpha_rewards
            log(f"    Alpha price: {alpha_price_tao:.6f} TAO (${alpha_price_tao * data.get('tao_price_usd', 190):.2f})")

    # 4. TAO price
    log("  [4/4] GET price/latest...")
    price_resp = api_get("api/price/latest/v1", params={"asset": "tao"})
    if price_resp and "data" in price_resp and len(price_resp["data"]) > 0:
        data["tao_price_usd"] = float(price_resp["data"][0].get("price", 0))
    else:
        data["tao_price_usd"] = 0

    # Alpha price from metagraph derivation
    data["alpha_price_tao"] = alpha_price_tao

    return data


# ── Message formatters ────────────────────────────────────────────────────────

def _progress_bar(score: int, max_score: int) -> str:
    """Generate unicode progress bar."""
    filled = round((score / max_score) * 10) if max_score > 0 else 0
    return "\u2593" * filled + "\u2591" * (10 - filled)


def _flow_fmt(val: float) -> str:
    """Format flow value from rao to TAO string."""
    tao = val * RAO_TO_TAO
    return f"{tao:+,.0f}"


def format_scheduled_report(signal, current_data: dict, conn) -> str:
    """Format the 6-hour scheduled report."""
    tao_usd = current_data.get("tao_price_usd", 0)
    alpha_tao = current_data.get("alpha_price_tao", 0)
    alpha_usd = alpha_tao * tao_usd

    lines = [
        "\u2501" * 20,
        f"\U0001f4ca SN{TARGET_NETUID} {TARGET_NAME} \u2014 6H REPORT",
        "\u2501" * 20,
        f"\U0001f522 Signal Score: <b>{signal.total_score}/100 ({signal.signal_type})</b>",
        "",
        f"\U0001f4c8 Emission: {current_data.get('emission_pct', 0) * 100:.1f}%",
        f"\U0001f4b0 Flow 1d: {_flow_fmt(current_data.get('net_flow_1d', 0))} TAO",
        f"\U0001f4b0 Flow 7d: {_flow_fmt(current_data.get('net_flow_7d', 0))} TAO",
        f"\U0001f4b0 Flow 30d: {_flow_fmt(current_data.get('net_flow_30d', 0))} TAO",
        f"\u26cf Miners: {current_data.get('active_miners', 0)}",
        f"\U0001f465 Validators: {current_data.get('active_validators', 0)}",
        f"\U0001f48e Alpha Price: {alpha_tao:.4f} TAO (${alpha_usd:.2f})",
        f"\U0001f4ca TAO/USD: ${tao_usd:.2f}",
        "",
        "INDICATORS:",
    ]

    for ind in signal.indicators:
        bar = _progress_bar(ind.score, ind.max_score)
        lines.append(f"{bar} {ind.name}: {ind.score}/{ind.max_score}")

    # Portfolio status
    portfolio = get_portfolio(conn)
    if portfolio["total_invested_usd"] > 0:
        n_pos = get_position_count(conn)
        pnl_pct = portfolio["current_pnl_pct"]
        pnl_usd = portfolio["total_invested_usd"] * (pnl_pct / 100)
        lines.append("")
        lines.append(f"\U0001f4e6 Portfolio: ${portfolio['total_invested_usd']:.0f} invested ({n_pos}/{10} tranches)")
        lines.append(f"\U0001f4ca Avg entry: {portfolio['avg_entry_price_tao']:.4f} TAO/alpha")
        lines.append(f"\U0001f4ca Current: {alpha_tao:.4f} TAO/alpha ({pnl_pct:+.1f}%)")
        lines.append(f"\U0001f4b5 Paper P&L: {'+' if pnl_usd >= 0 else ''}${pnl_usd:.2f}")

    lines.append("\u2501" * 20)
    return "\n".join(lines)


def format_signal_change(old_score: int, old_signal: str, new_score: int, new_signal: str,
                         changed_indicators: list[str]) -> str:
    """Format signal change alert."""
    lines = [
        f"\U0001f6a8 SN{TARGET_NETUID} SIGNAL CHANGE",
        f"OLD: {old_signal} ({old_score}/100)",
        f"NEW: <b>{new_signal} ({new_score}/100)</b>",
        "",
        "Changed indicators:",
    ]
    for desc in changed_indicators[:5]:
        lines.append(f"\u2705 {desc}")

    # Action recommendation
    if new_score >= 70:
        lines.append(f"\n\U0001f4a1 Action: Consider entering 1 DCA tranche (${100})")
    elif new_score >= 55:
        lines.append(f"\n\U0001f4a1 Action: Consider small accumulation position")
    elif new_score >= 40:
        lines.append(f"\n\U0001f4a1 Action: Hold off on new entries. Monitor.")
    elif new_score >= 25:
        lines.append(f"\n\U0001f4a1 Action: Do NOT enter new positions.")
    else:
        lines.append(f"\n\U0001f4a1 Action: Consider reducing position.")

    return "\n".join(lines)


def format_anomaly_alert(anomaly, old_score: int, new_score: int) -> str:
    """Format anomaly alert."""
    old_signal = score_to_signal(old_score)
    new_signal = score_to_signal(new_score)

    lines = [
        f"\u26a0\ufe0f SN{TARGET_NETUID} ANOMALY DETECTED",
        "",
        f"Type: <b>{anomaly.anomaly_type}</b>",
        f"Detail: {anomaly.detail}",
        f"Previous: {anomaly.previous_value}",
        "",
        f"Impact: Signal score {old_score} \u2192 {new_score} ({new_signal})",
        f"\U0001f4a1 Action: {anomaly.impact}",
    ]
    return "\n".join(lines)


def format_daily_summary(conn, current_data: dict, current_score: int) -> str:
    """Format daily summary."""
    today = datetime.now(timezone.utc).strftime("%B %d, %Y")
    scores = get_daily_scores(conn, hours=24)
    tao_usd = current_data.get("tao_price_usd", 0)
    alpha_tao = current_data.get("alpha_price_tao", 0)

    # Score trend
    if len(scores) >= 4:
        trend_scores = [scores[i] for i in range(0, len(scores), max(1, len(scores) // 4))][:4]
        trend_str = " \u2192 ".join(str(s) for s in trend_scores)
        if scores[-1] > scores[0] + 5:
            trend_dir = "RISING \u2197"
        elif scores[-1] < scores[0] - 5:
            trend_dir = "FALLING \u2198"
        else:
            trend_dir = "STABLE \u2192"
    else:
        trend_str = str(current_score)
        trend_dir = "N/A"

    avg_7d = sum(get_daily_scores(conn, hours=168)) // max(1, len(get_daily_scores(conn, hours=168))) if get_daily_scores(conn, hours=168) else current_score
    avg_signal = score_to_signal(avg_7d)

    lines = [
        f"\U0001f4cb SN{TARGET_NETUID} DAILY SUMMARY \u2014 {today}",
        "",
        f"Score trend (24h): {trend_str} ({trend_dir})",
        f"Emission: {current_data.get('emission_pct', 0) * 100:.1f}%",
        f"Net TAO today: {_flow_fmt(current_data.get('net_flow_1d', 0))} TAO",
        f"Alpha price: {alpha_tao:.4f} TAO (${alpha_tao * tao_usd:.2f})",
        f"Miners: {current_data.get('active_miners', 0)}",
        "",
        f"7-day score average: {avg_7d} ({avg_signal})",
    ]

    if current_score >= 70:
        lines.append("Recommendation: Score is in BUY zone. Good time for DCA entry.")
    elif current_score >= 55:
        lines.append("Recommendation: Accumulate zone. Consider small positions.")
    else:
        lines.append(f"Recommendation: Wait for score >70 for next DCA entry.")

    return "\n".join(lines)


def format_paper_buy_alert(buy_info: dict, signal_score: int) -> str:
    """Format paper buy execution alert."""
    lines = [
        f"\U0001f4b8 SN{TARGET_NETUID} PAPER BUY EXECUTED",
        "",
        f"Tranche: {buy_info['tranche']}/{10}",
        f"Amount: ${buy_info['amount_usd']:.0f} ({buy_info['amount_tao']:.4f} TAO)",
        f"Alpha price: {buy_info['alpha_price_tao']:.4f} TAO",
        f"Tokens acquired: {buy_info['alpha_tokens']:.2f} alpha",
        f"TAO/USD: ${buy_info['tao_price_usd']:.2f}",
        f"Signal score: {signal_score}/100",
        "",
        f"\U0001f4e6 Total invested: ${buy_info['total_invested']:.0f}",
    ]
    return "\n".join(lines)


# ── Main bot loop ─────────────────────────────────────────────────────────────

def main():
    log("=" * 60)
    log(f"SN{TARGET_NETUID} {TARGET_NAME} Signal Bot starting...")
    log("=" * 60)

    # Validate config
    if not TAOSTATS_API_KEY:
        log("FATAL: TAOSTATS_API_KEY not set!")
        sys.exit(1)
    if not TELEGRAM_BOT_TOKEN:
        log("WARNING: Telegram bot token not set — will log only")
    if not TELEGRAM_CHAT_ID:
        log("WARNING: Telegram chat ID not set — will log only")

    # Init DB
    from db import get_connection
    conn = get_connection()
    create_tables(conn)
    log("DB tables ready.")

    # State tracking
    last_report_ts = 0
    last_daily_ts = 0
    last_signal_type = None
    cycle_count = 0

    # Send startup message
    send_telegram(
        f"\U0001f680 SN{TARGET_NETUID} {TARGET_NAME} Signal Bot started!\n"
        f"Monitoring every {CYCLE_INTERVAL_SECONDS // 60} minutes.\n"
        f"Reports every {REPORT_INTERVAL_SECONDS // 3600} hours."
    )

    while True:
        try:
            cycle_count += 1
            now = time.time()
            now_dt = datetime.now(timezone.utc)
            log(f"\n--- Cycle {cycle_count} ({now_dt.strftime('%H:%M UTC')}) ---")

            # ── Step 1: Collect data ──────────────────────────────────────
            log("Collecting data from TaoStats...")
            current_data = collect_data()
            if not current_data:
                log("Data collection failed. Retrying next cycle.")
                time.sleep(CYCLE_INTERVAL_SECONDS)
                continue

            log(f"  Emission: {current_data.get('emission_pct', 0) * 100:.1f}%")
            log(f"  Flow 7d: {_flow_fmt(current_data.get('net_flow_7d', 0))} TAO")
            log(f"  Miners: {current_data.get('active_miners', 0)}")
            log(f"  TAO/USD: ${current_data.get('tao_price_usd', 0):.2f}")

            # ── Step 2: Get history for trend analysis ────────────────────
            # Refresh connection before reads to avoid stale streams
            try:
                conn.sync()
            except Exception:
                conn = get_connection()

            history = get_history(conn)
            previous = get_previous_reading(conn)

            # ── Step 3: Calculate signal ──────────────────────────────────
            log("Calculating signal...")
            signal = calculate_signal(
                current_data,
                [current_data] + history,  # Include current as first element
                current_data.get("validator_hhi", 0.5),
                current_data.get("second_emission", 0),
            )
            log(f"  Signal: {signal.total_score}/100 ({signal.signal_type})")
            for ind in signal.indicators:
                log(f"    {ind.name}: {ind.score}/{ind.max_score} — {ind.detail}")

            # ── Step 4: Store reading ─────────────────────────────────────
            store_reading(conn, current_data, signal.total_score, signal.signal_type)

            # ── Step 5: Check for anomalies ───────────────────────────────
            anomalies = detect_anomalies(current_data, previous)
            if anomalies:
                log(f"  {len(anomalies)} anomalies detected!")
                old_score = int(previous.get("signal_score", 0)) if previous else 0
                for a in anomalies:
                    log(f"    [{a.anomaly_type}] {a.detail}")
                    msg = format_anomaly_alert(a, old_score, signal.total_score)
                    send_telegram(msg)

            # ── Step 6: Check for signal threshold crossing ───────────────
            if previous and last_signal_type:
                old_score = int(previous.get("signal_score", 0))
                old_signal = score_to_signal(old_score)
                if signal.signal_type != old_signal:
                    log(f"  Signal change: {old_signal}→{signal.signal_type}")
                    changed = [ind.detail for ind in signal.indicators
                               if ind.score > 0]
                    msg = format_signal_change(
                        old_score, old_signal,
                        signal.total_score, signal.signal_type,
                        changed,
                    )
                    send_telegram(msg)

            last_signal_type = signal.signal_type

            # ── Step 7: Check paper buy conditions ────────────────────────
            alpha_price = current_data.get("alpha_price_tao", 0)
            tao_price = current_data.get("tao_price_usd", 0)
            if alpha_price > 0:
                update_portfolio_pnl(conn, alpha_price)

            buy_info = execute_paper_buy(conn, alpha_price, tao_price, signal.total_score)
            if buy_info:
                log(f"  Paper buy executed: tranche {buy_info['tranche']}")
                msg = format_paper_buy_alert(buy_info, signal.total_score)
                send_telegram(msg)

            # ── Step 8: Scheduled report (every 6h) ───────────────────────
            if now - last_report_ts >= REPORT_INTERVAL_SECONDS:
                log("  Sending 6h scheduled report...")
                msg = format_scheduled_report(signal, current_data, conn)
                send_telegram(msg)
                last_report_ts = now

            # ── Step 9: Daily summary (08:00 UTC) ─────────────────────────
            if now_dt.hour == DAILY_SUMMARY_HOUR_UTC and now - last_daily_ts >= 23 * 3600:
                log("  Sending daily summary...")
                msg = format_daily_summary(conn, current_data, signal.total_score)
                send_telegram(msg)
                last_daily_ts = now

            log(f"Cycle {cycle_count} complete. Next in {CYCLE_INTERVAL_SECONDS // 60}m.")

        except KeyboardInterrupt:
            log("Shutdown requested (Ctrl+C).")
            send_telegram(f"\U0001f6d1 SN{TARGET_NETUID} Signal Bot shutting down.")
            break
        except Exception as e:
            log(f"ERROR in cycle {cycle_count}: {e}")
            log(traceback.format_exc())
            # Try to send error notification
            try:
                send_telegram(
                    f"\u274c SN{TARGET_NETUID} Bot Error\n\n"
                    f"Cycle {cycle_count}: {str(e)[:200]}\n\n"
                    f"Bot will retry in {CYCLE_INTERVAL_SECONDS // 60} minutes."
                )
            except Exception:
                pass

            # Reconnect DB on error
            try:
                conn = get_connection()
            except Exception:
                pass

        # Wait for next cycle
        time.sleep(CYCLE_INTERVAL_SECONDS)


# ── One-shot mode for testing ─────────────────────────────────────────────────

def run_once():
    """Run a single collection + scoring cycle for testing."""
    log("=" * 60)
    log(f"SN{TARGET_NETUID} {TARGET_NAME} Signal Bot — ONE SHOT TEST")
    log("=" * 60)

    from db import get_connection
    conn = get_connection()
    create_tables(conn)

    # Collect
    log("\nCollecting data...")
    current_data = collect_data()
    if not current_data:
        log("FAILED to collect data!")
        return

    log("\nRaw data collected:")
    for k, v in current_data.items():
        if isinstance(v, float) and abs(v) > 1e6:
            log(f"  {k}: {v} (= {v * RAO_TO_TAO:,.2f} TAO)")
        else:
            log(f"  {k}: {v}")

    # History
    history = get_history(conn)
    previous = get_previous_reading(conn)
    log(f"\nHistory: {len(history)} past readings")

    # Signal
    log("\nCalculating signal...")
    signal = calculate_signal(
        current_data,
        [current_data] + history,
        current_data.get("validator_hhi", 0.5),
        current_data.get("second_emission", 0),
    )

    log(f"\n{'='*50}")
    log(f"SIGNAL: {signal.total_score}/100 ({signal.signal_type})")
    log(f"{'='*50}")
    for ind in signal.indicators:
        bar = _progress_bar(ind.score, ind.max_score)
        log(f"  {bar} {ind.name}: {ind.score}/{ind.max_score} — {ind.detail}")

    # Store
    store_reading(conn, current_data, signal.total_score, signal.signal_type)
    log("\nReading stored to DB.")

    # Anomalies
    anomalies = detect_anomalies(current_data, previous)
    if anomalies:
        log(f"\nAnomalies ({len(anomalies)}):")
        for a in anomalies:
            log(f"  [{a.anomaly_type}] {a.detail}")
    else:
        log("\nNo anomalies.")

    # Generate report text
    log("\n6H Report preview:")
    report = format_scheduled_report(signal, current_data, conn)
    print(report)

    conn.close()
    return signal, current_data


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--once":
        run_once()
    elif len(sys.argv) > 1 and sys.argv[1] == "--test-telegram":
        log("Testing Telegram connectivity...")
        success = send_telegram(
            f"\U0001f4e1 SN{TARGET_NETUID} {TARGET_NAME} Bot — Test message\n"
            f"Timestamp: {datetime.now(timezone.utc).isoformat()}\n"
            f"Status: Connected"
        )
        if success:
            log("Test message sent successfully!")
        else:
            log("Failed to send test message!")
    else:
        main()
