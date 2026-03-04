"""Signal engine for SN64 Chutes monitoring.

Calculates a composite ENTRY SCORE (0-100) from 7 indicators.
"""

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


# ── Individual indicator scorers ──────────────────────────────────────────────

def score_emission_trend(history: list[dict]) -> IndicatorResult:
    """Score emission trend over recent readings.

    history: list of dicts with 'emission_pct' and 'timestamp', newest first.
    """
    max_pts = WEIGHTS["emission_trend"]

    if not history or len(history) < 2:
        return IndicatorResult("Emission Trend", 10, max_pts, "Insufficient data")

    current = history[0].get("emission_pct", 0)

    # Check if emission is rising for 3+ consecutive readings
    rising_count = 0
    for i in range(len(history) - 1):
        if history[i].get("emission_pct", 0) > history[i + 1].get("emission_pct", 0):
            rising_count += 1
        else:
            break

    # Check stability: within +/-0.5% of mean over last ~24h (96 readings at 15min)
    recent_24h = history[:min(96, len(history))]
    emissions = [h.get("emission_pct", 0) for h in recent_24h]
    if emissions:
        mean_em = sum(emissions) / len(emissions)
        max_dev = max(abs(e - mean_em) for e in emissions) if emissions else 0
        is_stable = max_dev < 0.005  # 0.5%
    else:
        is_stable = False
        mean_em = current

    if rising_count >= 3:
        return IndicatorResult("Emission Trend", 25, max_pts,
                               f"Rising for {rising_count} readings ({current*100:.1f}%)")
    elif is_stable and len(recent_24h) >= 4:
        return IndicatorResult("Emission Trend", 20, max_pts,
                               f"Stable at {current*100:.1f}% (±{max_dev*100:.2f}%)")
    elif current > 0.10:
        return IndicatorResult("Emission Trend", 10, max_pts,
                               f"Declining but >{10}% ({current*100:.1f}%)")
    elif current > 0.08:
        return IndicatorResult("Emission Trend", 5, max_pts,
                               f"Low emission ({current*100:.1f}%)")
    else:
        return IndicatorResult("Emission Trend", 0, max_pts,
                               f"Very low emission ({current*100:.1f}%)")


def score_flow_momentum(current_data: dict) -> IndicatorResult:
    """Score flow momentum by comparing flow ratios across time windows."""
    max_pts = WEIGHTS["flow_momentum"]

    f1d = current_data.get("net_flow_1d", 0) * RAO_TO_TAO
    f7d = current_data.get("net_flow_7d", 0) * RAO_TO_TAO
    f30d = current_data.get("net_flow_30d", 0) * RAO_TO_TAO

    # Avoid division by zero
    ratio_1d_7d = (f1d / f7d * 100) if f7d != 0 else 0
    ratio_7d_30d = (f7d / f30d * 100) if f30d != 0 else 0

    if f7d <= 0 and f30d <= 0:
        return IndicatorResult("Flow Momentum", 0, max_pts,
                               f"Outflow: 7d={f7d:+,.0f}, 30d={f30d:+,.0f} TAO")

    if any(f < 0 for f in [f1d, f7d, f30d]):
        return IndicatorResult("Flow Momentum", 5, max_pts,
                               f"Mixed: 1d={f1d:+,.0f}, 7d={f7d:+,.0f}, 30d={f30d:+,.0f} TAO")

    if ratio_1d_7d > 20 and ratio_7d_30d > 30:
        return IndicatorResult("Flow Momentum", 25, max_pts,
                               f"Accelerating: 1d/7d={ratio_1d_7d:.0f}%, 7d/30d={ratio_7d_30d:.0f}%")
    elif ratio_1d_7d > 14 and ratio_7d_30d > 23:
        return IndicatorResult("Flow Momentum", 20, max_pts,
                               f"Healthy: 1d/7d={ratio_1d_7d:.0f}%, 7d/30d={ratio_7d_30d:.0f}%")
    elif ratio_1d_7d > 10:
        return IndicatorResult("Flow Momentum", 15, max_pts,
                               f"Decelerating: 1d/7d={ratio_1d_7d:.0f}%, all positive")
    else:
        return IndicatorResult("Flow Momentum", 10, max_pts,
                               f"Weak: 1d/7d={ratio_1d_7d:.0f}%")


def score_flow_magnitude(current_data: dict) -> IndicatorResult:
    """Score absolute flow magnitude."""
    max_pts = WEIGHTS["flow_magnitude"]

    f7d = current_data.get("net_flow_7d", 0) * RAO_TO_TAO

    if f7d > 5000:
        return IndicatorResult("Flow Magnitude", 15, max_pts, f"Strong: {f7d:+,.0f} TAO/7d")
    elif f7d > 2000:
        return IndicatorResult("Flow Magnitude", 12, max_pts, f"Good: {f7d:+,.0f} TAO/7d")
    elif f7d > 500:
        return IndicatorResult("Flow Magnitude", 8, max_pts, f"Moderate: {f7d:+,.0f} TAO/7d")
    elif f7d > 0:
        return IndicatorResult("Flow Magnitude", 5, max_pts, f"Weak: {f7d:+,.0f} TAO/7d")
    else:
        return IndicatorResult("Flow Magnitude", 0, max_pts, f"Negative: {f7d:+,.0f} TAO/7d")


def score_miner_health(history: list[dict]) -> IndicatorResult:
    """Score miner count trend over 7 days."""
    max_pts = WEIGHTS["miner_health"]

    if not history or len(history) < 2:
        current = history[0].get("active_miners", 0) if history else 0
        return IndicatorResult("Miner Health", 5, max_pts, f"{current} miners (no trend data)")

    current = history[0].get("active_miners", 0)
    # Look back ~7 days (672 readings at 15min)
    lookback = min(672, len(history) - 1)
    old = history[lookback].get("active_miners", 0)

    if old == 0:
        return IndicatorResult("Miner Health", 5, max_pts, f"{current} miners")

    change_pct = ((current - old) / old) * 100

    if current > old:
        return IndicatorResult("Miner Health", 10, max_pts,
                               f"Growing: {old}→{current} (+{change_pct:.0f}%)")
    elif abs(current - old) <= 2:
        return IndicatorResult("Miner Health", 7, max_pts,
                               f"Stable: {old}→{current}")
    elif change_pct > -10:
        return IndicatorResult("Miner Health", 4, max_pts,
                               f"Slight decline: {old}→{current} ({change_pct:.0f}%)")
    else:
        return IndicatorResult("Miner Health", 0, max_pts,
                               f"Declining: {old}→{current} ({change_pct:.0f}%)")


def score_validator_concentration(validator_hhi: float) -> IndicatorResult:
    """Score validator stake concentration (HHI index)."""
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
    """Score SN64 emission relative to #2 subnet."""
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
    """Score alpha price trend from stored data."""
    max_pts = WEIGHTS["alpha_price_trend"]

    if not history or len(history) < 2:
        return IndicatorResult("Alpha Price Trend", 3, max_pts, "Insufficient data")

    current = history[0].get("alpha_price_tao", 0)
    # Look back ~24h (96 readings at 15min)
    lookback_24h = min(96, len(history) - 1)
    old_24h = history[lookback_24h].get("alpha_price_tao", 0)

    if old_24h <= 0 or current <= 0:
        return IndicatorResult("Alpha Price Trend", 3, max_pts, "No price data")

    change_24h = ((current - old_24h) / old_24h) * 100

    if change_24h < -10:
        return IndicatorResult("Alpha Price Trend", 0, max_pts,
                               f"Crashing: {change_24h:+.1f}% in 24h")
    elif change_24h < -2:
        return IndicatorResult("Alpha Price Trend", 1, max_pts,
                               f"Declining: {change_24h:+.1f}% in 24h")
    elif change_24h <= 2:
        return IndicatorResult("Alpha Price Trend", 3, max_pts,
                               f"Stable: {change_24h:+.1f}% in 24h")
    else:
        return IndicatorResult("Alpha Price Trend", 5, max_pts,
                               f"Rising: {change_24h:+.1f}% in 24h")


# ── Composite scorer ─────────────────────────────────────────────────────────

def calculate_signal(current_data: dict, history: list[dict],
                     validator_hhi: float, second_emission: float) -> SignalResult:
    """Calculate composite signal score from all indicators.

    Args:
        current_data: Latest snapshot dict with all raw fields.
        history: List of past snapshots, newest first.
        validator_hhi: Current validator HHI index.
        second_emission: Emission pct of #2 subnet.

    Returns:
        SignalResult with total score, signal label, and indicator breakdown.
    """
    from sn64_config import score_to_signal

    indicators = [
        score_emission_trend(history),
        score_flow_momentum(current_data),
        score_flow_magnitude(current_data),
        score_miner_health(history),
        score_validator_concentration(validator_hhi),
        score_relative_dominance(current_data.get("emission_pct", 0), second_emission),
        score_alpha_price_trend(history),
    ]

    total = sum(ind.score for ind in indicators)
    signal_type = score_to_signal(total)

    return SignalResult(
        total_score=total,
        signal_type=signal_type,
        indicators=indicators,
        raw_data=current_data,
    )


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
                detail=f"Emission dropped {em_change:+.1f}% ({prev_em:.1f}%→{cur_em:.1f}%)",
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
            detail=f"Miners dropped {prev_miners}→{cur_miners} (-{prev_miners - cur_miners})",
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
                detail=f"Alpha price dropped {price_change:+.1f}% ({prev_price:.4f}→{cur_price:.4f} TAO)",
                previous_value=f"{prev_price:.4f} TAO",
                impact="Token value declining sharply",
            ))

    return anomalies
