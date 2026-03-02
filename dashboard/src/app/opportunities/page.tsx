import { getDb } from "@/lib/db";

export const dynamic = "force-dynamic";

interface Opportunity {
  netuid: number;
  name: string;
  opportunity_type: string;
  confidence: string;
  description: string;
  reasoning: string;
}

interface Anomaly {
  netuid: number;
  name: string;
  anomaly_type: string;
  description: string;
  severity: string;
}

interface Risk {
  netuid: number;
  name: string;
  risk_type: string;
  description: string;
}

function ConfidenceBadge({ level }: { level: string }) {
  const cls = level === "HIGH"
    ? "bg-green-500/20 text-green-400"
    : level === "MEDIUM"
    ? "bg-yellow-500/20 text-yellow-400"
    : "bg-blue-500/20 text-blue-400";
  return <span className={`text-xs font-bold px-2 py-0.5 rounded-full ${cls}`}>{level}</span>;
}

function SeverityBadge({ level }: { level: string }) {
  const cls = level === "HIGH"
    ? "bg-red-500/20 text-red-400"
    : level === "MEDIUM"
    ? "bg-yellow-500/20 text-yellow-400"
    : "bg-blue-500/20 text-blue-400";
  return <span className={`text-xs font-bold px-2 py-0.5 rounded-full ${cls}`}>{level}</span>;
}

function TypeIcon({ type }: { type: string }) {
  const icons: Record<string, string> = {
    FLOW_ACCELERATION: ">>",
    POTENTIAL_OVERSOLD: "!!",
    TOP_QUALITY: "**",
    EARLY_GROWTH: "++",
  };
  return <span className="text-indigo-400 font-mono text-xs">{icons[type] || "??"}</span>;
}

async function getData() {
  const reportRes = await getDb().execute(
    "SELECT report_json, timestamp FROM analysis_reports ORDER BY timestamp DESC LIMIT 1"
  );

  if (reportRes.rows.length === 0) return null;

  try {
    const report = JSON.parse(String(reportRes.rows[0].report_json));
    return {
      ...report,
      report_ts: Number(reportRes.rows[0].timestamp),
    };
  } catch {
    return null;
  }
}

export default async function OpportunitiesPage() {
  const report = await getData();

  if (!report || report.type !== "subnet_investment_analysis") {
    return (
      <div className="space-y-6">
        <h1 className="text-2xl font-bold">Opportunities</h1>
        <div className="card text-center py-12 text-[#8888a0]">
          No subnet analysis available. Run <code className="text-indigo-300">6_analyze_subnets.py</code> first.
        </div>
      </div>
    );
  }

  const opportunities: Opportunity[] = report.opportunities || [];
  const anomalies: Anomaly[] = report.anomalies || [];
  const risks: Risk[] = report.risks || [];
  const reportDate = report.date || new Date(report.report_ts * 1000).toLocaleString();

  // Group opportunities by type
  const byType: Record<string, Opportunity[]> = {};
  for (const o of opportunities) {
    if (!byType[o.opportunity_type]) byType[o.opportunity_type] = [];
    byType[o.opportunity_type].push(o);
  }

  const typeLabels: Record<string, string> = {
    FLOW_ACCELERATION: "Flow Acceleration",
    POTENTIAL_OVERSOLD: "Potential Oversold",
    TOP_QUALITY: "Top Quality Subnets",
    EARLY_GROWTH: "Early Growth",
  };

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold">Opportunities & Alerts</h1>
        <span className="text-xs text-[#8888a0]">Analysis: {reportDate}</span>
      </div>

      {/* Summary cards */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        <div className="card">
          <p className="text-xs text-[#8888a0]">Opportunities</p>
          <p className="text-2xl font-bold mt-1 text-green-400">{opportunities.length}</p>
        </div>
        <div className="card">
          <p className="text-xs text-[#8888a0]">Anomalies</p>
          <p className="text-2xl font-bold mt-1 text-yellow-400">{anomalies.length}</p>
        </div>
        <div className="card">
          <p className="text-xs text-[#8888a0]">Risk Warnings</p>
          <p className="text-2xl font-bold mt-1 text-red-400">{risks.length}</p>
        </div>
        <div className="card">
          <p className="text-xs text-[#8888a0]">Subnets Analyzed</p>
          <p className="text-2xl font-bold mt-1">{report.n_subnets}</p>
        </div>
      </div>

      {/* Opportunities by type */}
      {Object.entries(byType).map(([type, opps]) => (
        <div key={type} className="card">
          <div className="flex items-center gap-2 mb-4">
            <TypeIcon type={type} />
            <h3 className="text-sm font-bold">{typeLabels[type] || type}</h3>
            <span className="text-xs text-[#8888a0]">({opps.length})</span>
          </div>
          <div className="space-y-3">
            {opps.slice(0, 8).map((o, i) => (
              <div key={i} className="flex items-start gap-3 p-3 rounded-lg bg-white/[0.02] hover:bg-white/[0.04] transition-colors">
                <div className="flex-shrink-0 mt-0.5">
                  <ConfidenceBadge level={o.confidence} />
                </div>
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2 mb-1">
                    <span className="font-medium text-sm">Subnet {o.netuid}</span>
                    <span className="text-xs text-[#8888a0]">({o.name})</span>
                  </div>
                  <p className="text-sm">{o.description}</p>
                  <p className="text-xs text-[#8888a0] mt-1">{o.reasoning}</p>
                </div>
              </div>
            ))}
          </div>
        </div>
      ))}

      {/* Anomalies */}
      {anomalies.length > 0 && (
        <div className="card border-yellow-500/20">
          <h3 className="text-sm font-bold text-yellow-400 mb-4">Anomalies Detected</h3>
          <div className="space-y-2">
            {anomalies.slice(0, 15).map((a, i) => (
              <div key={i} className="flex items-start gap-3 py-2 border-b border-[#1e1e2e]/50 last:border-0">
                <SeverityBadge level={a.severity} />
                <div className="flex-1">
                  <span className="font-medium text-sm">SN{a.netuid}</span>
                  <span className="text-xs text-[#8888a0] ml-2">{a.anomaly_type.replace(/_/g, " ")}</span>
                  <p className="text-xs text-[#8888a0] mt-0.5">{a.description}</p>
                </div>
              </div>
            ))}
            {anomalies.length > 15 && (
              <p className="text-xs text-[#8888a0] text-center pt-2">
                +{anomalies.length - 15} more anomalies
              </p>
            )}
          </div>
        </div>
      )}

      {/* Risk warnings */}
      {risks.length > 0 && (
        <div className="card border-red-500/20">
          <h3 className="text-sm font-bold text-red-400 mb-4">Risk Warnings</h3>
          <div className="space-y-2">
            {risks.map((r, i) => (
              <div key={i} className="flex items-center gap-3 py-2 border-b border-[#1e1e2e]/50 last:border-0">
                <span className="text-red-400 text-sm font-mono">!!</span>
                <div className="flex-1">
                  <span className="font-medium text-sm">Subnet {r.netuid}</span>
                  <span className="text-xs text-[#8888a0] ml-2">({r.name})</span>
                  <p className="text-xs text-[#8888a0] mt-0.5">{r.description}</p>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
