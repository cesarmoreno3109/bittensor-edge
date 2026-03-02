import { getDb } from "@/lib/db";

export const dynamic = "force-dynamic";

interface SubnetScore {
  netuid: number;
  name: string;
  composite_score: number;
  emission_score: number;
  flow_score: number;
  dereg_safety_score: number;
  momentum_score: number;
  validator_health_score: number;
  stake_growth_score: number;
  risk_level: string;
  tao_flow_30d_tao?: number;
  tao_flow_7d_tao?: number;
}

interface OldAnalysis {
  name: string;
  metrics: Record<string, unknown>;
  edge: string;
  reasoning: string;
}

interface OldHypothesis {
  name: string;
  edge: string;
  reasoning: string;
}

function EdgeBadge({ level }: { level: string }) {
  const cls = level === "HIGH" ? "badge-high" : level === "MEDIUM" ? "badge-medium" : level === "LOW" ? "badge-low" : "badge-none";
  return (
    <span className={`${cls} text-xs font-bold px-2.5 py-1 rounded-full`}>
      {level}
    </span>
  );
}

function RiskBadge({ level }: { level: string }) {
  const cls = level === "LOW"
    ? "bg-green-500/20 text-green-400"
    : level === "MEDIUM"
    ? "bg-yellow-500/20 text-yellow-400"
    : "bg-red-500/20 text-red-400";
  return <span className={`text-xs font-bold px-2 py-0.5 rounded-full ${cls}`}>{level}</span>;
}

function ScoreBar({ value, max = 10 }: { value: number; max?: number }) {
  const pct = Math.min((value / max) * 100, 100);
  const color = value >= 7 ? "bg-green-500" : value >= 4 ? "bg-yellow-500" : "bg-red-500";
  return (
    <div className="flex items-center gap-2">
      <div className="flex-1 h-2 bg-[#1e1e2e] rounded-full overflow-hidden">
        <div className={`h-full ${color} rounded-full`} style={{ width: `${pct}%` }} />
      </div>
      <span className="text-xs font-mono w-8 text-right">{value.toFixed(1)}</span>
    </div>
  );
}

function MetricDisplay({ label, value }: { label: string; value: unknown }) {
  if (typeof value === "object" && value !== null) {
    return (
      <div className="mb-2">
        <span className="text-xs text-[#8888a0]">{label}:</span>
        <div className="ml-3 mt-1">
          {Object.entries(value as Record<string, unknown>).slice(0, 8).map(([k, v]) => (
            <div key={k} className="text-xs text-[#8888a0]">
              <span className="text-indigo-300">{k}</span>: {String(v)}
            </div>
          ))}
        </div>
      </div>
    );
  }
  return (
    <div className="flex justify-between text-sm py-0.5">
      <span className="text-[#8888a0]">{label}</span>
      <span className="font-mono">{String(value)}</span>
    </div>
  );
}

async function getData() {
  const res = await getDb().execute("SELECT report_json FROM analysis_reports ORDER BY timestamp DESC LIMIT 1");
  if (res.rows.length === 0) return null;
  try {
    return JSON.parse(String(res.rows[0].report_json));
  } catch {
    return null;
  }
}

export default async function AnalysisPage() {
  const report = await getData();

  if (!report) {
    return (
      <div className="space-y-6">
        <h1 className="text-2xl font-bold">Analysis</h1>
        <div className="card text-center py-12 text-[#8888a0]">
          No analysis reports yet. Run pipeline scripts to generate.
        </div>
      </div>
    );
  }

  // Check if this is the new subnet analysis format
  if (report.type === "subnet_investment_analysis") {
    const topSubnets: SubnetScore[] = report.top_subnets || [];

    return (
      <div className="space-y-6">
        <h1 className="text-2xl font-bold">Subnet Analysis Report</h1>
        <p className="text-sm text-[#8888a0]">
          Date: {report.date} | Subnets: {report.n_subnets} | Opportunities: {report.n_opportunities} | Anomalies: {report.n_anomalies}
        </p>

        {/* Top 10 with score breakdown */}
        <div className="card">
          <h3 className="text-sm font-bold text-indigo-300 mb-4">Top 10 Subnets — Score Breakdown</h3>
          <div className="space-y-4">
            {topSubnets.slice(0, 10).map((s, i) => (
              <div key={s.netuid} className="p-4 rounded-lg bg-white/[0.02]">
                <div className="flex items-center gap-3 mb-3">
                  <span className="text-lg font-bold text-[#8888a0] w-8">{i + 1}.</span>
                  <span className="font-bold">SN{s.netuid}</span>
                  <span className="text-sm text-[#8888a0]">{s.name}</span>
                  <span className="font-bold text-lg ml-auto">{s.composite_score.toFixed(1)}</span>
                  <RiskBadge level={s.risk_level} />
                </div>
                <div className="grid grid-cols-2 md:grid-cols-3 gap-x-6 gap-y-1">
                  <div>
                    <p className="text-xs text-[#8888a0]">Flow (25%)</p>
                    <ScoreBar value={s.flow_score} />
                  </div>
                  <div>
                    <p className="text-xs text-[#8888a0]">Emission (20%)</p>
                    <ScoreBar value={s.emission_score} />
                  </div>
                  <div>
                    <p className="text-xs text-[#8888a0]">Dereg Safety (20%)</p>
                    <ScoreBar value={s.dereg_safety_score} />
                  </div>
                  <div>
                    <p className="text-xs text-[#8888a0]">Momentum (15%)</p>
                    <ScoreBar value={s.momentum_score} />
                  </div>
                  <div>
                    <p className="text-xs text-[#8888a0]">Validator Health (10%)</p>
                    <ScoreBar value={s.validator_health_score} />
                  </div>
                  <div>
                    <p className="text-xs text-[#8888a0]">Stake Growth (10%)</p>
                    <ScoreBar value={s.stake_growth_score} />
                  </div>
                </div>
                {(s.tao_flow_30d_tao != null || s.tao_flow_7d_tao != null) && (
                  <div className="flex gap-4 mt-2 text-xs text-[#8888a0]">
                    {s.tao_flow_30d_tao != null && (
                      <span>30d: <span className={s.tao_flow_30d_tao >= 0 ? "text-green-400" : "text-red-400"}>
                        {s.tao_flow_30d_tao >= 0 ? "+" : ""}{s.tao_flow_30d_tao.toFixed(0)} TAO
                      </span></span>
                    )}
                    {s.tao_flow_7d_tao != null && (
                      <span>7d: <span className={s.tao_flow_7d_tao >= 0 ? "text-green-400" : "text-red-400"}>
                        {s.tao_flow_7d_tao >= 0 ? "+" : ""}{s.tao_flow_7d_tao.toFixed(0)} TAO
                      </span></span>
                    )}
                  </div>
                )}
              </div>
            ))}
          </div>
        </div>

        {/* All scored subnets compact view */}
        <div className="card overflow-x-auto">
          <h3 className="text-sm text-[#8888a0] mb-3">All Scored Subnets (11-20)</h3>
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-3">
            {topSubnets.slice(10, 20).map((s, i) => (
              <div key={s.netuid} className="flex items-center gap-3 p-2 rounded bg-white/[0.02]">
                <span className="text-sm text-[#8888a0] w-6">{i + 11}.</span>
                <span className="font-bold text-sm">SN{s.netuid}</span>
                <span className="text-xs text-[#8888a0] flex-1 truncate">{s.name}</span>
                <span className="font-mono text-sm">{s.composite_score.toFixed(1)}</span>
                <RiskBadge level={s.risk_level} />
              </div>
            ))}
          </div>
        </div>
      </div>
    );
  }

  // Fallback: old analysis format
  const analyses: OldAnalysis[] = report.analyses || [];
  const hypotheses: OldHypothesis[] = report.hypotheses || [];

  return (
    <div className="space-y-6">
      <h1 className="text-2xl font-bold">Analysis Report</h1>
      <p className="text-sm text-[#8888a0]">
        Date: {report.date} | Data: {report.data_range} | {report.n_prices} prices | {report.n_events} events
      </p>

      {hypotheses.length > 0 && (
        <div className="card border-indigo-500/30">
          <h3 className="text-sm font-bold text-indigo-300 mb-3">Top Hypotheses</h3>
          <div className="space-y-3">
            {hypotheses.map((h, i) => (
              <div key={i} className="flex items-start gap-3">
                <span className="text-lg font-bold text-[#8888a0] w-6">{i + 1}.</span>
                <div className="flex-1">
                  <div className="flex items-center gap-2 mb-1">
                    <span className="font-medium">{h.name}</span>
                    <EdgeBadge level={h.edge} />
                  </div>
                  <p className="text-sm text-[#8888a0]">{h.reasoning}</p>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        {analyses.map((a, i) => (
          <div key={i} className="card">
            <div className="flex items-center justify-between mb-3">
              <h3 className="font-medium text-sm">{a.name}</h3>
              <EdgeBadge level={a.edge} />
            </div>
            <div className="space-y-1 mb-3">
              {Object.entries(a.metrics).map(([k, v]) => (
                <MetricDisplay key={k} label={k} value={v} />
              ))}
            </div>
            <p className="text-xs text-[#8888a0] border-t border-[#1e1e2e] pt-2 mt-2">{a.reasoning}</p>
          </div>
        ))}
      </div>
    </div>
  );
}
