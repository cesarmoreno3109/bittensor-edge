import { db } from "@/lib/db";

export const dynamic = "force-dynamic";

interface Analysis {
  name: string;
  metrics: Record<string, unknown>;
  edge: string;
  reasoning: string;
}

interface Hypothesis {
  name: string;
  edge: string;
  reasoning: string;
}

async function getData() {
  const res = await db.execute("SELECT report_json FROM analysis_reports ORDER BY timestamp DESC LIMIT 1");
  if (res.rows.length === 0) return null;
  try {
    return JSON.parse(String(res.rows[0].report_json));
  } catch {
    return null;
  }
}

function EdgeBadge({ level }: { level: string }) {
  const cls = level === "HIGH" ? "badge-high" : level === "MEDIUM" ? "badge-medium" : level === "LOW" ? "badge-low" : "badge-none";
  return (
    <span className={`${cls} text-xs font-bold px-2.5 py-1 rounded-full`}>
      {level}
    </span>
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

export default async function AnalysisPage() {
  const report = await getData();

  if (!report) {
    return (
      <div className="space-y-6">
        <h1 className="text-2xl font-bold">Analysis</h1>
        <div className="card text-center py-12 text-[#8888a0]">
          No analysis reports yet. Run <code className="text-indigo-300">3_explore.py</code> to generate.
        </div>
      </div>
    );
  }

  const analyses: Analysis[] = report.analyses || [];
  const hypotheses: Hypothesis[] = report.hypotheses || [];

  return (
    <div className="space-y-6">
      <h1 className="text-2xl font-bold">Analysis Report</h1>
      <p className="text-sm text-[#8888a0]">
        Date: {report.date} | Data: {report.data_range} | {report.n_prices} prices | {report.n_events} events
      </p>

      {/* Top hypotheses */}
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

      {/* Individual analyses */}
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
