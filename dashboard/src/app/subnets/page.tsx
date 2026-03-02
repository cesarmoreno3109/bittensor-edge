import { getDb } from "@/lib/db";
import { SubnetFlowChart, SubnetScoreChart, EmissionVsFlowScatter } from "@/components/Charts";

export const dynamic = "force-dynamic";

const RAO = 1e-9;

function RiskBadge({ level }: { level: string }) {
  const cls = level === "LOW"
    ? "bg-green-500/20 text-green-400"
    : level === "MEDIUM"
    ? "bg-yellow-500/20 text-yellow-400"
    : "bg-red-500/20 text-red-400";
  return <span className={`text-xs font-bold px-2 py-0.5 rounded-full ${cls}`}>{level}</span>;
}

function fmtFlow(v: number | null): string {
  if (v == null) return "—";
  const tao = v * RAO;
  const sign = tao >= 0 ? "+" : "";
  if (Math.abs(tao) >= 1000) return `${sign}${(tao / 1000).toFixed(1)}K`;
  return `${sign}${tao.toFixed(0)}`;
}

async function getData() {
  // Get latest analysis report with subnet scores
  const reportRes = await getDb().execute(
    "SELECT report_json FROM analysis_reports ORDER BY timestamp DESC LIMIT 1"
  );

  let report = null;
  if (reportRes.rows.length > 0) {
    try {
      report = JSON.parse(String(reportRes.rows[0].report_json));
    } catch {}
  }

  // Get latest subnet data directly from DB
  const subnetRes = await getDb().execute(`
    SELECT netuid, name, emission_pct, validator_count, miner_count,
           tao_flow_24h, tao_flow_7d, tao_flow_30d, ema_tao_flow, active_keys,
           registration_cost, emission_raw
    FROM taostats_subnets
    WHERE snapshot_ts = (SELECT MAX(snapshot_ts) FROM taostats_subnets)
    ORDER BY emission_raw DESC
  `);

  const subnets = subnetRes.rows.map((r) => ({
    netuid: Number(r.netuid),
    name: String(r.name || `SN${r.netuid}`),
    emission_pct: Number(r.emission_pct || 0),
    validator_count: Number(r.validator_count || 0),
    miner_count: Number(r.miner_count || 0),
    tao_flow_24h: Number(r.tao_flow_24h || 0),
    tao_flow_7d: Number(r.tao_flow_7d || 0),
    tao_flow_30d: Number(r.tao_flow_30d || 0),
    ema_tao_flow: Number(r.ema_tao_flow || 0),
    active_keys: Number(r.active_keys || 0),
  }));

  // Get network stats
  const netRes = await getDb().execute(
    "SELECT * FROM taostats_network_stats ORDER BY timestamp DESC LIMIT 1"
  );
  const netStats = netRes.rows.length > 0 ? {
    total_subnets: Number(netRes.rows[0].total_subnets || 0),
    total_validators: Number(netRes.rows[0].total_validators || 0),
    total_miners: Number(netRes.rows[0].total_miners || 0),
    block_number: Number(netRes.rows[0].block_number || 0),
  } : null;

  return { report, subnets, netStats };
}

export default async function SubnetsPage() {
  const { report, subnets, netStats } = await getData();

  const scores = report?.all_scores || [];
  const scoreMap = new Map(scores.map((s: Record<string, unknown>) => [s.netuid, s]));

  // Build sorted list with scores
  const rankedSubnets = subnets
    .filter((s) => s.netuid !== 0)
    .map((s) => {
      const sc = scoreMap.get(s.netuid) as Record<string, number | string> | undefined;
      return {
        ...s,
        score: sc ? Number(sc.composite_score) : 0,
        risk: sc ? String(sc.risk_level) : "MEDIUM",
        emission_score: sc ? Number(sc.emission_score) : 0,
        flow_score: sc ? Number(sc.flow_score) : 0,
      };
    })
    .sort((a, b) => b.score - a.score);

  // Chart data
  const flowChartData = rankedSubnets
    .map((s) => ({
      netuid: s.netuid,
      name: `SN${s.netuid}`,
      flow_30d: Math.round(s.tao_flow_30d * RAO),
      flow_7d: Math.round(s.tao_flow_7d * RAO),
    }))
    .sort((a, b) => Math.abs(b.flow_30d) - Math.abs(a.flow_30d));

  const scoreChartData = rankedSubnets.slice(0, 20).map((s) => ({
    netuid: s.netuid,
    name: `SN${s.netuid}`,
    score: s.score,
    risk: s.risk,
  }));

  const scatterData = rankedSubnets.map((s) => ({
    netuid: s.netuid,
    name: `SN${s.netuid}`,
    emission: s.emission_pct,
    flow: Math.round(s.tao_flow_30d * RAO),
    score: s.score,
  }));

  return (
    <div className="space-y-6">
      <h1 className="text-2xl font-bold">Subnet Investment Rankings</h1>

      {/* Network stats */}
      {netStats && (
        <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
          <div className="card">
            <p className="text-xs text-[#8888a0]">Total Subnets</p>
            <p className="text-2xl font-bold mt-1">{netStats.total_subnets}</p>
          </div>
          <div className="card">
            <p className="text-xs text-[#8888a0]">Total Validators</p>
            <p className="text-2xl font-bold mt-1">{netStats.total_validators.toLocaleString()}</p>
          </div>
          <div className="card">
            <p className="text-xs text-[#8888a0]">Total Miners</p>
            <p className="text-2xl font-bold mt-1">{netStats.total_miners.toLocaleString()}</p>
          </div>
          <div className="card">
            <p className="text-xs text-[#8888a0]">Block</p>
            <p className="text-2xl font-bold mt-1">{netStats.block_number.toLocaleString()}</p>
          </div>
        </div>
      )}

      {/* Charts */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <SubnetScoreChart data={scoreChartData} />
        <EmissionVsFlowScatter data={scatterData} />
      </div>
      <SubnetFlowChart data={flowChartData} />

      {/* Subnet ranking table */}
      <div className="card overflow-x-auto">
        <h3 className="text-sm text-[#8888a0] mb-3">All Subnets Ranked by Composite Score</h3>
        <table className="w-full text-sm">
          <thead>
            <tr className="text-left text-[#8888a0] border-b border-[#1e1e2e]">
              <th className="pb-2 pr-3">Rank</th>
              <th className="pb-2 pr-3">NetUID</th>
              <th className="pb-2 pr-3">Name</th>
              <th className="pb-2 pr-3">Score</th>
              <th className="pb-2 pr-3">Risk</th>
              <th className="pb-2 pr-3">Emission</th>
              <th className="pb-2 pr-3">Flow 24h</th>
              <th className="pb-2 pr-3">Flow 7d</th>
              <th className="pb-2 pr-3">Flow 30d</th>
              <th className="pb-2 pr-3">Validators</th>
              <th className="pb-2">Keys</th>
            </tr>
          </thead>
          <tbody>
            {rankedSubnets.map((s, i) => (
              <tr key={s.netuid} className="border-b border-[#1e1e2e]/50 hover:bg-white/5">
                <td className="py-1.5 pr-3 text-[#8888a0]">{i + 1}</td>
                <td className="py-1.5 pr-3 font-bold">{s.netuid}</td>
                <td className="py-1.5 pr-3 text-xs max-w-[120px] truncate">{s.name}</td>
                <td className="py-1.5 pr-3 font-bold font-mono">{s.score.toFixed(1)}</td>
                <td className="py-1.5 pr-3"><RiskBadge level={s.risk} /></td>
                <td className="py-1.5 pr-3 font-mono text-xs">{(s.emission_pct * 100).toFixed(2)}%</td>
                <td className={`py-1.5 pr-3 font-mono text-xs ${s.tao_flow_24h >= 0 ? "text-green-400" : "text-red-400"}`}>
                  {fmtFlow(s.tao_flow_24h)}
                </td>
                <td className={`py-1.5 pr-3 font-mono text-xs ${s.tao_flow_7d >= 0 ? "text-green-400" : "text-red-400"}`}>
                  {fmtFlow(s.tao_flow_7d)}
                </td>
                <td className={`py-1.5 pr-3 font-mono text-xs ${s.tao_flow_30d >= 0 ? "text-green-400" : "text-red-400"}`}>
                  {fmtFlow(s.tao_flow_30d)}
                </td>
                <td className="py-1.5 pr-3">{s.validator_count}</td>
                <td className="py-1.5">{s.active_keys}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
