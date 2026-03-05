"""Signal engine for SN64 Chutes monitoring — CALIBRATED v2.

Uses smoothed moving averages instead of point-in-time readings to prevent
score oscillation from noise. Includes anti-flicker logic with hysteresis
bands, minimum hold times, and score rate limiting.
"""

import time
import statistics
from dataclasses import dataclass
from sn64_config import WEIGHTS, RAO_TO_TAO


@dataclass
class IndicatorResult:
    name: str
    score: int
    max_score: int
    detail: str


@dataclass
class SignalResult:
    total_score: int
    signal_type: str
    indicators: list  # list of IndicatorResult
    raw_data: dict
    raw_score: int       # unsmoothed composite score
    display_score: int   # rate-limited display score
    data_quality: str    # "CALIBRATING", "LIMITED", "FULL"


# ── Calibration status check ─────────────────────────────────────────────────

def check_data_quality(history: list[dict]) -> tuple[str, float]:
    """Check if we have enough data for smoothed indicators.

    Returns:
        (quality_label, confidence_multiplier)
        - "CALIBRATING": <24 readings (<6h) — no signals
        - "LIMITED": 24-95 readings (6-24h) — reduced confidence
        - "FULL": 96+ readings (24h+) — full confidence
    """
    n = len(history)
    if n < 24:
        return "CALIBRATING", 0.0
    elif n < 96:
        return "LIMITED", n / 96.0
    else:
        return "FULL", 1.0


# ── Individual indicator scorers (SMOOTHED) ──────────────────────────────────

def score_emission_trend(history: list[dict]) -> IndicatorResult:
    """Score emission trend using 6H moving average vs 24H average.

    Uses last 24 readings (6h) averaged vs last 96 readings (24h) averaged.
    """
    max_pts = WEIGHTS["emission_trend"]

    if not history or len(history) < 2:
        return IndicatorResult("Emission Trend", 10, max_pts, "Insufficient data")

    # Gather emission values (newest first in history)
    all_emissions = [h.get("emission_pct", 0) for h in history]

    # 6H average (last 24 readings)
    emissions_6h = all_emissions[:min(24, len(all_emissions))]
    avg_emission_6h = statistics.mean(emissions_6h) if emissions_6h else 0

    # 24H average (last 96 readings)
    emissions_24h = all_emissions[:min(96, len(all_emissions))]
    avg_emission_24h = statistics.mean(emissions_24h) if emissions_24h else avg_emission_6h

    # Standard deviation of 6h window for stability check
    std_dev_6h = statistics.stdev(emissions_6h) if len(emissions_6h) >= 2 else 0

    avg_6h_pct = avg_emission_6h * 100
    avg_24h_pct = avg_emission_24h * 100
    diff_pct = avg_6h_pct - avg_24h_pct
    std_pct = std_dev_6h * 100

    # Scoring based on smoothed averages
    if avg_6h_pct > avg_24h_pct + 0.5:
        return IndicatorResult("Emission Trend", 25, max_pts,
                               f"Rising: 6h avg {avg_6h_pct:.1f}% > 24h avg {avg_24h_pct:.1f}% (+{diff_pct:.1f}%)")
    elif std_pct < 0.5 and avg_6h_pct > 10:
        return IndicatorResult("Emission Trend", 20, max_pts,
                               f"Stable at {avg_6h_pct:.1f}% (\u03c3={std_pct:.2f}%)")
    elif avg_6h_pct <= avg_24h_pct and avg_6h_pct > 10:
        return IndicatorResult("Emission Trend", 10, max_pts,
                               f"Declining but strong: 6h {avg_6h_pct:.1f}% < 24h {avg_24h_pct:.1f}%")
    elif avg_6h_pct > 8:
        return IndicatorResult("Emission Trend", 5, max_pts,
                               f"Low emission: 6h avg {avg_6h_pct:.1f}%")
    else:
        return IndicatorResult("Emission Trend", 0, max_pts,
                               f"Very low: 6h avg {avg_6h_pct:.1f}%")


def score_flow_momentum(history: list[dict]) -> IndicatorResult:
    """Score flow momentum using 4H smoothed ratios.

    Averages net_flow_1d, net_flow_7d, net_flow_30d over last 16 readings (4h).
    """
    max_pts = WEIGHTS["flow_momentum"]

    if not history or len(history) < 2:
        return IndicatorResult("Flow Momentum", 10, max_pts, "Insufficient data")

    # 4H smoothed values (last 16 readings)
    window = min(16, len(history))
    smoothed_1d = statistics.mean([h.get("net_flow_1d", 0) * RAO_TO_TAO for h in history[:window]])
    smoothed_7d = statistics.mean([h.get("net_flow_7d", 0) * RAO_TO_TAO for h in history[:window]])
    smoothed_30d = statistics.mean([h.get("net_flow_30d", 0) * RAO_TO_TAO for h in history[:window]])

    # Smoothed ratio
    smoothed_ratio = (smoothed_1d / smoothed_7d * 100) if smoothed_7d != 0 else 0

    all_positive = smoothed_1d > 0 and smoothed_7d > 0 and smoothed_30d > 0

    if smoothed_7d <= 0 and smoothed_30d <= 0:
        return IndicatorResult("Flow Momentum", 0, max_pts,
                               f"Outflow: sm7d={smoothed_7d:+,.0f}, sm30d={smoothed_30d:+,.0f} TAO")

    if any(f < 0 for f in [smoothed_1d, smoothed_7d, smoothed_30d]):
        return IndicatorResult("Flow Momentum", 5, max_pts,
                               f"Mixed: sm1d={smoothed_1d:+,.0f}, sm7d={smoothed_7d:+,.0f}, sm30d={smoothed_30d:+,.0f} TAO")

    if smoothed_ratio > 20 and all_positive:
        return IndicatorResult("Flow Momentum", 25, max_pts,
                               f"Accelerating: sm1d/7d={smoothed_ratio:.0f}% (4h avg)")
    elif smoothed_ratio > 14 and all_positive:
        return IndicatorResult("Flow Momentum", 20, max_pts,
                               f"Healthy: sm1d/7d={smoothed_ratio:.0f}% (4h avg)")
    elif smoothed_ratio > 10 and all_positive:
        return IndicatorResult("Flow Momentum", 15, max_pts,
                               f"Decelerating: sm1d/7d={smoothed_ratio:.0f}% (4h avg)")
    else:
        return IndicatorResult("Flow Momentum", 10, max_pts,
                               f"Weak: sm1d/7d={smoothed_ratio:.0f}%")


def score_flow_magnitude(history: list[dict]) -> IndicatorResult:
    """Score absolute flow magnitude using 4H smoothed 7d flow."""
    max_pts = WEIGHTS["flow_magnitude"]

    if not history:
        return IndicatorResult("Flow Magnitude", 5, max_pts, "No data")

    # 4H smoothed 7d flow
    window = min(16, len(history))
    smoothed_7d = statistics.mean([h.get("net_flow_7d", 0) * RAO_TO_TAO for h in history[:window]])

    if smoothed_7d > 5000:
        return IndicatorResult("Flow Magnitude", 15, max_pts, f"Strong: sm7d={smoothed_7d:+,.0f} TAO")
    elif smoothed_7d > 2000:
        return IndicatorResult("Flow Magnitude", 12, max_pts, f"Good: sm7d={smoothed_7d:+,.0f} TAO")
    elif smoothed_7d > 500:
        return IndicatorResult("Flow Magnitude", 8, max_pts, f"Moderate: sm7d={smoothed_7d:+,.0f} TAO")
    elif smoothed_7d > 0:
        return IndicatorResult("Flow Magnitude", 5, max_pts, f"Weak: sm7d={smoothed_7d:+,.0f} TAO")
    else:
        return IndicatorResult("Flow Magnitude", 0, max_pts, f"Negative: sm7d={smoothed_7d:+,.0f} TAO")


def score_miner_health(history: list[dict]) -> IndicatorResult:
    """Score miner count trend using 24H comparison.

    Compares current miners vs reading from ~24h ago.
    """
    max_pts = WEIGHTS["miner_health"]

    if not history or len(history) < 2:
        current = history[0].get("active_miners", 0) if history else 0
        return IndicatorResult("Miner Health", 5, max_pts, f"{current} miners (no trend data)")

    current = history[0].get("active_miners", 0)

    # Find reading from ~24h ago (index 96 at 15-min intervals)
    idx_24h = min(96, len(history) - 1)
    miners_24h_ago = history[idx_24h].get("active_miners", 0)

    if miners_24h_ago == 0:
        return IndicatorResult("Miner Health", 5, max_pts, f"{current} miners")

    change_pct = ((current - miners_24h_ago) / miners_24h_ago) * 100

    if current > miners_24h_ago:
        return IndicatorResult("Miner Health", 10, max_pts,
                               f"Growing: {miners_24h_ago}\u2192{current} 24h (+{change_pct:.0f}%)")
    elif abs(current - miners_24h_ago) <= 1:
        return IndicatorResult("Miner Health", 7, max_pts,
                               f"Stable: {miners_24h_ago}\u2192{current} 24h")
    elif change_pct > -10:
        return IndicatorResult("Miner Health", 4, max_pts,
                               f"Slight decline: {miners_24h_ago}\u2192{current} 24h ({change_pct:.0f}%)")
    else:
        return IndicatorResult("Miner Health", 0, max_pts,
                               f"Declining: {miners_24h_ago}\u2192{current} 24h ({change_pct:.0f}%)")


def score_validator_concentration(validator_hhi: float) -> IndicatorResult:
    """Score validator stake concentration (HHI index). Unchanged — already stable."""
    max_pts = WEIGHTS["validator_concentration"]

    if validator_hhi < 0.15:
        return IndicatorResult("Validator Concentration", 10, max_pts,
                               f"Well distributed (HHI={validator_hhi:.3f})")
    elif validator_hhi < 0.25:
        return IndicatorResult("Validator Concentration", 7, max_pts,
                               f"Moderate (HHI={validator_hhi:.3f})")
    elif validator_hhi < 0.40:
        return IndicatorResult("Validator Concentration", 4, max_pts,
                               f"Concentrated (HHI={validator_hhi:.3f})")
    else:
        return IndicatorResult("Validator Concentration", 0, max_pts,
                               f"Highly concentrated (HHI={validator_hhi:.3f})")


def score_relative_dominance(sn64_emission: float, second_emission: float) -> IndicatorResult:
    """Score SN64 emission relative to #2 subnet. Unchanged — already stable."""
    max_pts = WEIGHTS["relative_dominance"]

    if second_emission <= 0:
        return IndicatorResult("Relative Dominance", 10, max_pts, "No competitor")

    ratio = sn64_emission / second_emission

    if ratio > 2.0:
        return IndicatorResult("Relative Dominance", 10, max_pts,
                               f"Clear leader ({ratio:.1f}x #2)")
    elif ratio > 1.5:
        return IndicatorResult("Relative Dominance", 7, max_pts,
                               f"Leading ({ratio:.1f}x #2)")
    elif ratio > 1.0:
        return IndicatorResult("Relative Dominance", 4, max_pts,
                               f"Narrow lead ({ratio:.1f}x #2)")
    else:
        return IndicatorResult("Relative Dominance", 0, max_pts,
                               f"Lost leadership ({ratio:.1f}x #2)")


def score_alpha_price_trend(history: list[dict]) -> IndicatorResult:
    """Score alpha price trend using 12H moving average comparison.

    Compares avg of last 48 readings (12h) vs previous 48 readings (12-24h ago).
    """
    max_pts = WEIGHTS["alpha_price_trend"]

    if not history or len(history) < 4:
        return IndicatorResult("Alpha Price Trend", 3, max_pts, "Insufficient data")

    prices = [h.get("alpha_price_tao", 0) for h in history if h.get("alpha_price_tao", 0) > 0]

    if len(prices) < 4:
        return IndicatorResult("Alpha Price Trend", 3, max_pts, "No price data")

    # 12H average (last 48 readings)
    window_12h = min(48, len(prices))
    avg_alpha_12h = statistics.mean(prices[:window_12h])

    # Previous 12H average (readings 48-96)
    if len(prices) > window_12h:
        prev_window = min(48, len(prices) - window_12h)
        avg_alpha_prev_12h = statistics.mean(prices[window_12h:window_12h + prev_window])
    else:
        # Not enough data for previous window — use what we have
        avg_alpha_prev_12h = avg_alpha_12h

    if avg_alpha_prev_12h <= 0:
        return IndicatorResult("Alpha Price Trend", 3, max_pts, "No prev price data")

    change_pct = ((avg_alpha_12h - avg_alpha_prev_12h) / avg_alpha_prev_12h) * 100

    if change_pct < -10:
        return IndicatorResult("Alpha Price Trend", 0, max_pts,
                               f"Crashing: 12h avg {change_pct:+.1f}%")
    elif change_pct < -2:
        return IndicatorResult("Alpha Price Trend", 1, max_pts,
                               f"Declining: 12h avg {change_pct:+.1f}%")
    elif change_pct <= 2:
        return IndicatorResult("Alpha Price Trend", 3, max_pts,
                               f"Stable: 12h avg {change_pct:+.1f}%")
    else:
        return IndicatorResult("Alpha Price Trend", 5, max_pts,
                               f"Rising: 12h avg {change_pct:+.1f}%")


# ── Composite scorer ─────────────────────────────────────────────────────────

def calculate_signal(current_data: dict, history: list[dict],
                     validator_hhi: float, second_emission: float) -> SignalResult:
    """Calculate composite signal score from all indicators.

    Now uses smoothed indicators and returns both raw and display scores.
    The anti-flicker logic is applied externally by apply_signal_smoothing().

    Args:
        current_data: Latest snapshot dict with all raw fields.
        history: List of past snapshots, newest first.
        validator_hhi: Current validator HHI index.
        second_emission: Emission pct of #2 subnet.

    Returns:
        SignalResult with raw score, indicators, and data quality.
    """
    from sn64_config import score_to_signal

    # Check data quality
    quality, confidence = check_data_quality(history)

    if quality == "CALIBRATING":
        # Not enough data — return calibrating state
        return SignalResult(
            total_score=50,
            signal_type="CALIBRATING",
            indicators=[],
            raw_data=current_data,
            raw_score=50,
            display_score=50,
            data_quality=quality,
        )

    # All smoothed indicators now take history
    indicators = [
        score_emission_trend(history),
        score_flow_momentum(history),
        score_flow_magnitude(history),
        score_miner_health(history),
        score_validator_concentration(validator_hhi),
        score_relative_dominance(current_data.get("emission_pct", 0), second_emission),
        score_alpha_price_trend(history),
    ]

    raw_total = sum(ind.score for ind in indicators)
    signal_type = score_to_signal(raw_total)

    return SignalResult(
        total_score=raw_total,
        signal_type=signal_type,
        indicators=indicators,
        raw_data=current_data,
        raw_score=raw_total,
        display_score=raw_total,  # Will be overwritten by apply_signal_smoothing
        data_quality=quality,
    )


# ── Anti-flicker smoothing ───────────────────────────────────────────────────

# Hysteresis bands: to ENTER a signal level, score must exceed by +5
# To EXIT a signal level, score must drop by -5 below threshold
HYSTERESIS_BANDS = {
    "STRONG BUY": {"enter": 90, "exit": 80},   # Normal: 85
    "BUY":        {"enter": 75, "exit": 65},    # Normal: 70
    "ACCUMULATE": {"enter": 60, "exit": 50},    # Normal: 55
    "WAIT":       {"enter": 45, "exit": 35},    # Normal: 40
    "CAUTION":    {"enter": 30, "exit": 20},    # Normal: 25
    "EXIT":       {"enter": 0,  "exit": 0},     # Always accessible
}

# Signal levels ordered from highest to lowest
SIGNAL_LEVELS = ["STRONG BUY", "BUY", "ACCUMULATE", "WAIT", "CAUTION", "EXIT"]

# Minimum hold time: 6 hours = 24 cycles at 15 min each
MIN_HOLD_SECONDS = 6 * 3600

# Max score change per cycle: 8 points
MAX_SCORE_CHANGE_PER_CYCLE = 8


def get_signal_state(conn) -> dict:
    """Read current signal state from DB."""
    try:
        res = conn.execute("SELECT current_signal, signal_since, display_score, last_raw_score FROM sn64_signal_state WHERE id = 1")
        row = res.fetchone()
        if row:
            return {
                "current_signal": row[0],
                "signal_since": int(row[1]),
                "display_score": float(row[2]),
                "last_raw_score": float(row[3]),
            }
    except Exception:
        pass
    return {
        "current_signal": "WAIT",
        "signal_since": 0,
        "display_score": 50,
        "last_raw_score": 50,
    }


def update_signal_state(conn, signal: str, since: int, display_score: float, raw_score: float):
    """Update signal state in DB."""
    conn.execute(
        """INSERT OR REPLACE INTO sn64_signal_state
           (id, current_signal, signal_since, display_score, last_raw_score)
           VALUES (1, ?, ?, ?, ?)""",
        (signal, since, display_score, raw_score),
    )
    conn.commit()


def _determine_signal_with_hysteresis(display_score: float, current_signal: str) -> str:
    """Determine what signal the display_score maps to with hysteresis.

    The current signal has 'sticky' behavior — it requires crossing
    the enter/exit thresholds rather than the simple thresholds.
    """
    # Check if we should move UP to a higher signal
    for level in SIGNAL_LEVELS:
        if level == current_signal:
            break
        band = HYSTERESIS_BANDS[level]
        if display_score >= band["enter"]:
            return level

    # Check if we should move DOWN from current signal
    current_band = HYSTERESIS_BANDS.get(current_signal)
    if current_band and display_score < current_band["exit"]:
        # Find the appropriate lower signal
        found_current = False
        for level in SIGNAL_LEVELS:
            if level == current_signal:
                found_current = True
                continue
            if found_current:
                band = HYSTERESIS_BANDS[level]
                if display_score >= band["exit"] or level == "EXIT":
                    return level

    return current_signal


def apply_signal_smoothing(conn, raw_score: int, raw_signal_type: str) -> tuple[int, str, bool]:
    """Apply anti-flicker logic to raw signal score.

    Returns:
        (display_score, display_signal, signal_changed)
    """
    state = get_signal_state(conn)
    prev_display = state["display_score"]
    prev_signal = state["current_signal"]
    signal_since = state["signal_since"]
    now = int(time.time())

    # 1. RATE LIMITER: Cap score change to +/-8 per cycle
    delta = raw_score - prev_display
    clamped_delta = max(min(delta, MAX_SCORE_CHANGE_PER_CYCLE), -MAX_SCORE_CHANGE_PER_CYCLE)
    display_score = int(prev_display + clamped_delta)
    display_score = max(0, min(100, display_score))

    # 2. HYSTERESIS: Determine signal with sticky thresholds
    candidate_signal = _determine_signal_with_hysteresis(display_score, prev_signal)

    # 3. MINIMUM HOLD TIME: Check if current signal held long enough
    hold_duration = now - signal_since if signal_since > 0 else MIN_HOLD_SECONDS + 1

    signal_changed = False
    if candidate_signal != prev_signal:
        if hold_duration >= MIN_HOLD_SECONDS:
            # Signal has been held long enough — allow change
            display_signal = candidate_signal
            signal_since = now
            signal_changed = True
        else:
            # Not held long enough — keep current signal
            display_signal = prev_signal
    else:
        display_signal = prev_signal

    # 4. Update state in DB
    update_signal_state(conn, display_signal, signal_since, display_score, raw_score)

    return display_score, display_signal, signal_changed


# ── Anomaly detection ────────────────────────────────────────────────────────

@dataclass
class Anomaly:
    anomaly_type: str
    detail: str
    previous_value: str
    impact: str


def detect_anomalies(current_data: dict, previous_data: dict | None) -> list[Anomaly]:
    """Detect anomalies by comparing current vs previous readings."""
    from sn64_config import (
        ANOMALY_EMISSION_DROP_PCT,
        ANOMALY_MINER_DROP_COUNT,
        ANOMALY_ALPHA_PRICE_DROP_PCT,
    )

    anomalies = []
    if not previous_data:
        return anomalies

    # 1. Emission drop
    cur_em = current_data.get("emission_pct", 0) * 100
    prev_em = previous_data.get("emission_pct", 0) * 100
    if prev_em > 0:
        em_change = cur_em - prev_em
        if em_change < -ANOMALY_EMISSION_DROP_PCT:
            anomalies.append(Anomaly(
                anomaly_type="EMISSION DROP",
                detail=f"Emission dropped {em_change:+.1f}% ({prev_em:.1f}%\u2192{cur_em:.1f}%)",
                previous_value=f"{prev_em:.1f}%",
                impact="May indicate loss of validator support",
            ))

    # 2. Flow reversal
    for window, label in [("net_flow_1d", "1d"), ("net_flow_7d", "7d")]:
        cur_flow = current_data.get(window, 0) * RAO_TO_TAO
        prev_flow = previous_data.get(window, 0) * RAO_TO_TAO
        if prev_flow > 0 and cur_flow < 0:
            anomalies.append(Anomaly(
                anomaly_type="FLOW REVERSAL",
                detail=f"{label} flow turned negative ({cur_flow:+,.0f} TAO)",
                previous_value=f"{prev_flow:+,.0f} TAO",
                impact="Capital outflow detected",
            ))

    # 3. Miner drop
    cur_miners = current_data.get("active_miners", 0)
    prev_miners = previous_data.get("active_miners", 0)
    if prev_miners > 0 and (prev_miners - cur_miners) > ANOMALY_MINER_DROP_COUNT:
        anomalies.append(Anomaly(
            anomaly_type="MINER EXODUS",
            detail=f"Miners dropped {prev_miners}\u2192{cur_miners} (-{prev_miners - cur_miners})",
            previous_value=str(prev_miners),
            impact="Network capacity declining rapidly",
        ))

    # 4. Alpha price crash
    cur_price = current_data.get("alpha_price_tao", 0)
    prev_price = previous_data.get("alpha_price_tao", 0)
    if prev_price > 0 and cur_price > 0:
        price_change = ((cur_price - prev_price) / prev_price) * 100
        if price_change < -ANOMALY_ALPHA_PRICE_DROP_PCT:
            anomalies.append(Anomaly(
                anomaly_type="ALPHA PRICE CRASH",
                detail=f"Alpha price dropped {price_change:+.1f}% ({prev_price:.4f}\u2192{cur_price:.4f} TAO)",
                previous_value=f"{prev_price:.4f} TAO",
                impact="Token value declining sharply",
            ))

    return anomalies
