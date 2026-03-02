#!/usr/bin/env python3
"""Phase 6: Subnet Investment Analysis — scoring, anomalies, opportunities.

Reads data from taostats_* tables and produces a comprehensive analysis report.
"""

import sys
import os
import json
import math
import time
from datetime import datetime, timezone
from dataclasses import dataclass, asdict
from typing import Optional

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def log(msg: str):
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    print(f"[{ts}] {msg}")


# ── Data Classes ──────────────────────────────────────────────────────────────

@dataclass
class SubnetScore:
    netuid: int
    name: str
    composite_score: float
    emission_score: float
    flow_score: float
    dereg_safety_score: float
    momentum_score: float
    validator_health_score: float
    stake_growth_score: float
    # Raw metrics
    emission_pct: float
    tao_flow_30d: float
    tao_flow_7d: float
    tao_flow_24h: float
    validator_count: int
    miner_count: int
    ema_tao_flow: float
    active_keys: int
    risk_level: str  # LOW, MEDIUM, HIGH


@dataclass
class Anomaly:
    netuid: int
    name: str
    anomaly_type: str
    description: str
    severity: str  # LOW, MEDIUM, HIGH


@dataclass
class Opportunity:
    netuid: int
    name: str
    opportunity_type: str
    confidence: str  # LOW, MEDIUM, HIGH
    description: str
    reasoning: str


# ── Scoring Functions ─────────────────────────────────────────────────────────

def normalize(values: list, reverse: bool = False) -> list:
    """Min-max normalize a list to [0, 1]."""
    if not values:
        return []
    mn = min(values)
    mx = max(values)
    if mx == mn:
        return [0.5] * len(values)
    if reverse:
        return [(mx - v) / (mx - mn) for v in values]
    return [(v - mn) / (mx - mn) for v in values]


def herfindahl_index(stakes: list) -> float:
    """Calculate Herfindahl-Hirschman Index for validator concentration.
    Lower = more decentralized = healthier. Returns 0-1 scale.
    """
    if not stakes or sum(stakes) == 0:
        return 1.0
    total = sum(stakes)
    shares = [s / total for s in stakes]
    hhi = sum(s ** 2 for s in shares)
    return hhi


def score_subnets(subnets: list, validators_by_subnet: dict) -> list[SubnetScore]:
    """Score each subnet using weighted composite model.

    Weights:
    - TAO flow 30d: 25%
    - Emission share: 20%
    - Deregistration safety: 20%
    - Price momentum (7d flow as proxy): 15%
    - Validator health: 10%
    - Stake growth: 10%
    """
    if not subnets:
        return []

    # Skip netuid 0 (root network)
    subnets = [s for s in subnets if s["netuid"] != 0]
    if not subnets:
        return []

    # Extract raw values
    emissions = [float(s.get("emission_pct") or s.get("emission_raw") or 0) for s in subnets]
    flows_30d = [float(s.get("tao_flow_30d") or 0) for s in subnets]
    flows_7d = [float(s.get("tao_flow_7d") or 0) for s in subnets]
    flows_24h = [float(s.get("tao_flow_24h") or 0) for s in subnets]
    ema_flows = [float(s.get("ema_tao_flow") or 0) for s in subnets]

    # Normalize scores (0-1)
    emission_norm = normalize(emissions)
    flow_30d_norm = normalize(flows_30d)
    flow_7d_norm = normalize(flows_7d)
    flow_24h_norm = normalize(flows_24h)

    # Dereg safety: higher ema_tao_flow = safer from deregistration
    ema_norm = normalize(ema_flows)

    # Validator health: lower HHI = healthier
    hhi_values = []
    for s in subnets:
        netuid = s["netuid"]
        vals = validators_by_subnet.get(netuid, [])
        if vals:
            stakes = [float(v.get("stake_tao") or 0) for v in vals if v.get("stake_tao")]
            hhi = herfindahl_index(stakes)
        else:
            hhi = 0.5  # Default when no validator data
        hhi_values.append(hhi)
    validator_health_norm = normalize(hhi_values, reverse=True)  # Lower HHI = higher score

    # Stake growth proxy: positive 7d flow relative to 30d
    stake_growth = []
    for i, s in enumerate(subnets):
        f30 = flows_30d[i]
        f7 = flows_7d[i]
        if abs(f30) > 0.01:
            growth = (f7 / abs(f30)) if f30 != 0 else 0
        else:
            growth = 0
        stake_growth.append(growth)
    stake_growth_norm = normalize(stake_growth)

    results = []
    for i, s in enumerate(subnets):
        netuid = s["netuid"]
        name = s.get("name", f"Subnet {netuid}")

        e_score = emission_norm[i]
        f_score = flow_30d_norm[i]
        d_score = ema_norm[i]
        m_score = flow_7d_norm[i]
        v_score = validator_health_norm[i]
        sg_score = stake_growth_norm[i]

        composite = (
            f_score * 0.25 +
            e_score * 0.20 +
            d_score * 0.20 +
            m_score * 0.15 +
            v_score * 0.10 +
            sg_score * 0.10
        )

        # Risk level based on composite + flow direction
        if composite >= 0.6 and flows_30d[i] >= 0:
            risk = "LOW"
        elif composite >= 0.3:
            risk = "MEDIUM"
        else:
            risk = "HIGH"

        results.append(SubnetScore(
            netuid=netuid,
            name=name,
            composite_score=round(composite * 10, 2),  # Scale to 0-10
            emission_score=round(e_score * 10, 2),
            flow_score=round(f_score * 10, 2),
            dereg_safety_score=round(d_score * 10, 2),
            momentum_score=round(m_score * 10, 2),
            validator_health_score=round(v_score * 10, 2),
            stake_growth_score=round(sg_score * 10, 2),
            emission_pct=emissions[i],
            tao_flow_30d=flows_30d[i],
            tao_flow_7d=flows_7d[i],
            tao_flow_24h=flows_24h[i],
            validator_count=int(s.get("validator_count") or 0),
            miner_count=int(s.get("miner_count") or 0),
            ema_tao_flow=ema_flows[i],
            active_keys=int(s.get("active_keys") or 0),
            risk_level=risk,
        ))

    results.sort(key=lambda x: x.composite_score, reverse=True)
    return results


# ── Anomaly Detection ─────────────────────────────────────────────────────────

def detect_anomalies(subnets: list, validators_by_subnet: dict) -> list[Anomaly]:
    """Detect anomalies in subnet data."""
    anomalies = []

    # Filter out root network
    subnets = [s for s in subnets if s.get("netuid", 0) != 0]

    # 1. Unusual TAO flow reversals
    for s in subnets:
        netuid = s.get("netuid", 0)
        name = s.get("name", f"Subnet {netuid}")
        f7 = float(s.get("tao_flow_7d") or 0)
        f30 = float(s.get("tao_flow_30d") or 0)
        f24 = float(s.get("tao_flow_24h") or 0)

        # Flow reversal: 30d positive but 7d negative (or vice versa)
        if f30 > 0 and f7 < 0 and abs(f7) > abs(f30) * 0.3:
            anomalies.append(Anomaly(
                netuid=netuid,
                name=name,
                anomaly_type="TAO_FLOW_REVERSAL",
                description=f"30d flow: {f30:.2f} TAO (positive) but 7d flow: {f7:.2f} TAO (reversal)",
                severity="MEDIUM",
            ))

        # Large single-day flow spike
        if abs(f24) > 0 and abs(f7) > 0 and abs(f24) > abs(f7) * 0.5:
            anomalies.append(Anomaly(
                netuid=netuid,
                name=name,
                anomaly_type="FLOW_SPIKE",
                description=f"24h flow ({f24:.2f} TAO) is >50% of 7d flow ({f7:.2f} TAO)",
                severity="LOW",
            ))

    # 2. Validator concentration warnings
    for netuid, vals in validators_by_subnet.items():
        if not vals:
            continue
        name = f"Subnet {netuid}"
        # Find matching subnet for name
        for s in subnets:
            if s.get("netuid") == netuid:
                name = s.get("name", name)
                break

        stakes = [float(v.get("stake_tao") or 0) for v in vals if v.get("stake_tao")]
        if not stakes:
            continue
        total = sum(stakes)
        if total == 0:
            continue

        max_share = max(stakes) / total
        if max_share > 0.5:
            anomalies.append(Anomaly(
                netuid=netuid,
                name=name,
                anomaly_type="VALIDATOR_CONCENTRATION",
                description=f"Single validator controls {max_share*100:.1f}% of stake",
                severity="HIGH",
            ))
        elif max_share > 0.3:
            anomalies.append(Anomaly(
                netuid=netuid,
                name=name,
                anomaly_type="VALIDATOR_CONCENTRATION",
                description=f"Top validator has {max_share*100:.1f}% of stake",
                severity="MEDIUM",
            ))

    # 3. Subnets with very few active keys (potential deregistration risk)
    for s in subnets:
        netuid = s.get("netuid", 0)
        name = s.get("name", f"Subnet {netuid}")
        active = int(s.get("active_keys") or 0)
        max_neurons = int(s.get("max_neurons") or 256)
        if active > 0 and active < 10:
            anomalies.append(Anomaly(
                netuid=netuid,
                name=name,
                anomaly_type="LOW_ACTIVITY",
                description=f"Only {active} active keys (max: {max_neurons})",
                severity="HIGH",
            ))

    return anomalies


# ── Opportunity Detection ─────────────────────────────────────────────────────

def detect_opportunities(scores: list[SubnetScore], subnets: list) -> list[Opportunity]:
    """Identify investment opportunities."""
    opportunities = []

    # Build lookup for raw data
    subnet_map = {s.get("netuid"): s for s in subnets}

    for sc in scores:
        s = subnet_map.get(sc.netuid, {})

        # 1. Flow accelerating but score hasn't caught up
        if sc.tao_flow_7d > 0 and sc.tao_flow_30d > 0:
            weekly_rate = sc.tao_flow_7d
            monthly_rate = sc.tao_flow_30d / 4.3  # weekly average
            if monthly_rate > 0 and weekly_rate > monthly_rate * 1.3:
                acceleration = ((weekly_rate / monthly_rate) - 1) * 100
                if acceleration > 50:
                    conf = "HIGH"
                elif acceleration > 30:
                    conf = "MEDIUM"
                else:
                    conf = "LOW"
                opportunities.append(Opportunity(
                    netuid=sc.netuid,
                    name=sc.name,
                    opportunity_type="FLOW_ACCELERATION",
                    confidence=conf,
                    description=f"TAO flow accelerating +{acceleration:.0f}% WoW vs monthly avg",
                    reasoning=f"7d flow: {sc.tao_flow_7d:.2f} TAO vs monthly weekly avg: {monthly_rate:.2f} TAO. Score: {sc.composite_score:.1f}/10",
                ))

        # 2. High emission but negative recent flow (potential oversold)
        if sc.emission_score > 5 and sc.tao_flow_7d < 0 and sc.tao_flow_30d < 0:
            opportunities.append(Opportunity(
                netuid=sc.netuid,
                name=sc.name,
                opportunity_type="POTENTIAL_OVERSOLD",
                confidence="LOW",
                description=f"High emission ({sc.emission_pct:.6f}) but negative flows — potential oversold",
                reasoning=f"Emission score: {sc.emission_score:.1f}/10. 7d flow: {sc.tao_flow_7d:.2f}, 30d: {sc.tao_flow_30d:.2f}",
            ))

        # 3. Strong score with good validator health
        if sc.composite_score > 7 and sc.validator_health_score > 5:
            opportunities.append(Opportunity(
                netuid=sc.netuid,
                name=sc.name,
                opportunity_type="TOP_QUALITY",
                confidence="HIGH",
                description=f"Top composite score ({sc.composite_score:.1f}/10) with healthy validators",
                reasoning=f"Flow: {sc.flow_score:.1f}, Emission: {sc.emission_score:.1f}, Validator health: {sc.validator_health_score:.1f}",
            ))

        # 4. New/low activity subnet with growing flow
        if sc.active_keys < 50 and sc.tao_flow_7d > 0 and sc.tao_flow_24h > 0:
            opportunities.append(Opportunity(
                netuid=sc.netuid,
                name=sc.name,
                opportunity_type="EARLY_GROWTH",
                confidence="LOW",
                description=f"Small subnet ({sc.active_keys} keys) with positive inflows",
                reasoning=f"24h flow: {sc.tao_flow_24h:.2f}, 7d: {sc.tao_flow_7d:.2f}. Early-stage growth signal.",
            ))

    # Sort by confidence
    conf_order = {"HIGH": 0, "MEDIUM": 1, "LOW": 2}
    opportunities.sort(key=lambda x: conf_order.get(x.confidence, 3))
    return opportunities


# ── Risk Assessment ───────────────────────────────────────────────────────────

def assess_risks(scores: list[SubnetScore], anomalies: list[Anomaly]) -> list[dict]:
    """Generate risk warnings."""
    risks = []

    # Subnets scored HIGH risk
    for sc in scores:
        if sc.risk_level == "HIGH":
            risks.append({
                "netuid": sc.netuid,
                "name": sc.name,
                "risk_type": "LOW_SCORE",
                "description": f"Low composite score ({sc.composite_score:.1f}/10), negative flows",
            })

    # Add concentrated validator risks from anomalies
    for a in anomalies:
        if a.anomaly_type == "VALIDATOR_CONCENTRATION" and a.severity == "HIGH":
            risks.append({
                "netuid": a.netuid,
                "name": a.name,
                "risk_type": "VALIDATOR_CONCENTRATION",
                "description": a.description,
            })

    return risks[:10]  # Top 10 risks


# ── Report Generation ─────────────────────────────────────────────────────────

def generate_report(scores: list[SubnetScore], anomalies: list[Anomaly],
                    opportunities: list[Opportunity], risks: list[dict]) -> str:
    """Generate text report for console output."""
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    lines = []
    lines.append("=" * 75)
    lines.append("BITTENSOR SUBNET INVESTMENT ANALYSIS")
    lines.append(f"Date: {today}")
    lines.append(f"Subnets analyzed: {len(scores)}")
    lines.append("=" * 75)

    # Top 10 by score
    lines.append("")
    lines.append("TOP 10 SUBNETS BY COMPOSITE SCORE:")
    lines.append(f"{'Rank':<5} {'NetUID':<7} {'Name':<25} {'Score':<7} {'Emission':<12} {'Flow(30d)':<14} {'Flow(7d)':<12} {'Risk'}")
    lines.append("-" * 95)
    for i, sc in enumerate(scores[:10]):
        name = (sc.name[:22] + "...") if len(sc.name) > 25 else sc.name
        lines.append(
            f"{i+1:<5} {sc.netuid:<7} {name:<25} {sc.composite_score:<7.1f} "
            f"{sc.emission_pct:<12.6f} {sc.tao_flow_30d:<14.2f} {sc.tao_flow_7d:<12.2f} {sc.risk_level}"
        )

    # Anomalies
    if anomalies:
        lines.append("")
        lines.append(f"ANOMALIES DETECTED ({len(anomalies)}):")
        for a in anomalies[:10]:
            icon = {"HIGH": "!!!", "MEDIUM": "!!", "LOW": "!"}[a.severity]
            lines.append(f"  [{icon}] Subnet {a.netuid} ({a.name}): {a.description}")

    # Opportunities
    if opportunities:
        lines.append("")
        lines.append(f"OPPORTUNITIES ({len(opportunities)}):")
        for i, o in enumerate(opportunities[:10]):
            lines.append(f"  {i+1}. [{o.confidence}] Subnet {o.netuid} ({o.name}): {o.description}")
            lines.append(f"     -> {o.reasoning}")

    # Risks
    if risks:
        lines.append("")
        lines.append(f"RISK WARNINGS ({len(risks)}):")
        for r in risks[:5]:
            lines.append(f"  - Subnet {r['netuid']} ({r['name']}): {r['description']}")

    lines.append("")
    lines.append("=" * 75)
    return "\n".join(lines)


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    print("\n" + "=" * 70)
    print("BITTENSOR EDGE — PHASE 6: SUBNET ANALYSIS")
    print("=" * 70 + "\n")

    from db import get_connection
    conn = get_connection()

    # ── Load latest subnet data ───────────────────────────────────────────
    log("Loading subnet data from DB...")
    try:
        res = conn.execute(
            """SELECT snapshot_ts, netuid, name, emission_pct, validator_count, miner_count,
                      tao_flow_24h, tao_flow_7d, tao_flow_30d, ema_tao_flow, active_keys,
                      registration_cost, emission_raw
               FROM taostats_subnets
               WHERE snapshot_ts = (SELECT MAX(snapshot_ts) FROM taostats_subnets)
               ORDER BY netuid"""
        )
        rows = res.fetchall()
    except Exception as e:
        log(f"ERROR loading subnets: {e}")
        conn.close()
        sys.exit(1)

    if not rows:
        log("No subnet data found. Run 5_collect_taostats.py first.")
        conn.close()
        sys.exit(1)

    cols = ["snapshot_ts", "netuid", "name", "emission_pct", "validator_count", "miner_count",
            "tao_flow_24h", "tao_flow_7d", "tao_flow_30d", "ema_tao_flow", "active_keys",
            "registration_cost", "emission_raw"]
    subnets = [dict(zip(cols, row)) for row in rows]
    log(f"  Loaded {len(subnets)} subnets")

    # ── Load validator data ───────────────────────────────────────────────
    log("Loading validator data from DB...")
    validators_by_subnet = {}
    try:
        res = conn.execute(
            """SELECT netuid, hotkey, stake_tao, nominators, dominance, take, rank, name
               FROM taostats_validators
               WHERE snapshot_ts = (SELECT MAX(snapshot_ts) FROM taostats_validators WHERE netuid = taostats_validators.netuid)"""
        )
        for row in res.fetchall():
            netuid = int(row[0])
            if netuid not in validators_by_subnet:
                validators_by_subnet[netuid] = []
            validators_by_subnet[netuid].append({
                "hotkey": row[1],
                "stake_tao": row[2],
                "nominators": row[3],
                "dominance": row[4],
                "take": row[5],
                "rank": row[6],
                "name": row[7],
            })
    except Exception as e:
        log(f"  Warning loading validators: {e}")

    total_v = sum(len(v) for v in validators_by_subnet.values())
    log(f"  Loaded validators for {len(validators_by_subnet)} subnets ({total_v} total)")

    # ── Score subnets ─────────────────────────────────────────────────────
    log("Scoring subnets...")
    scores = score_subnets(subnets, validators_by_subnet)
    log(f"  Scored {len(scores)} subnets")

    # ── Detect anomalies ──────────────────────────────────────────────────
    log("Detecting anomalies...")
    anomalies = detect_anomalies(subnets, validators_by_subnet)
    log(f"  Found {len(anomalies)} anomalies")

    # ── Detect opportunities ──────────────────────────────────────────────
    log("Detecting opportunities...")
    opportunities = detect_opportunities(scores, subnets)
    log(f"  Found {len(opportunities)} opportunities")

    # ── Assess risks ──────────────────────────────────────────────────────
    log("Assessing risks...")
    risks = assess_risks(scores, anomalies)
    log(f"  Found {len(risks)} risk warnings")

    # ── Generate report ───────────────────────────────────────────────────
    report_text = generate_report(scores, anomalies, opportunities, risks)
    print("\n" + report_text)

    # ── Save to DB ────────────────────────────────────────────────────────
    log("Saving analysis report to DB...")
    report_json = {
        "date": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        "type": "subnet_investment_analysis",
        "n_subnets": len(scores),
        "n_anomalies": len(anomalies),
        "n_opportunities": len(opportunities),
        "n_risks": len(risks),
        "top_subnets": [asdict(s) for s in scores[:20]],
        "all_scores": [asdict(s) for s in scores],
        "anomalies": [asdict(a) for a in anomalies],
        "opportunities": [asdict(o) for o in opportunities],
        "risks": risks,
    }

    timestamp = int(time.time())
    try:
        conn.execute(
            "INSERT OR REPLACE INTO analysis_reports (timestamp, report_json) VALUES (?, ?)",
            (timestamp, json.dumps(report_json)),
        )
        conn.commit()
        conn.sync()
        log("  Report saved to analysis_reports table.")
    except Exception as e:
        log(f"  Error saving report: {e}")

    conn.close()
    log("Phase 6 complete.")


if __name__ == "__main__":
    main()
