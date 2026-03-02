import { getDb } from "@/lib/db";
import { PriceChart } from "@/components/Charts";

export const dynamic = "force-dynamic";

const RAO = 1e-9;

function fmtFlow(v: number): string {
  const tao = v * RAO;
  const sign = tao >= 0 ? "+" : "";
  if (Math.abs(tao) >= 1000) return `${sign}${(tao / 1000).toFixed(1)}K`;
  return `${sign}${tao.toFixed(0)}`;
}

async function getData() {
  const [pricesRes, apiRes, countRes] = await Promise.all([
    getDb().execute("SELECT timestamp, open, high, low, close, volume FROM tao_prices ORDER BY timestamp"),
    getDb().execute("SELECT api_name, status, latency_ms, last_checked FROM api_status"),
    getDb().execute("SELECT COUNT(*) as cnt, MIN(timestamp) as min_ts, MAX(timestamp) as max_ts FROM tao_prices"),
  ]);

  const prices = pricesRes.rows.map((r) => ({
    timestamp: Number(r.timestamp),
    open: Number(r.open),
    high: Number(r.high),
    low: Number(r.low),
    close: Number(r.close),
    volume: Number(r.volume || 0),
  }));

  const apis = apiRes.rows.map((r) => ({
    name: String(r.api_name),
    status: String(r.status),
    latency: Number(r.latency_ms),
    lastChecked: Number(r.last_checked),
  }));

  const stats = countRes.rows[0];
  const count = Number(stats?.cnt || 0);
  const minTs = Number(stats?.min_ts || 0);
  const maxTs = Number(stats?.max_ts || 0);

  const current = prices.length > 0 ? prices[prices.length - 1].close : 0;
  const first = prices.length > 0 ? prices[0].close : 0;
  const change30d = first > 0 ? ((current - first) / first) * 100 : 0;

  // Volatility (std of daily returns)
  let volatility = 0;
  if (prices.length > 24) {
    const daily = prices.filter((_, i) => i % 24 === 0).map((p) => p.close);
    const rets = daily.slice(1).map((p, i) => (p - daily[i]) / daily[i]);
    const mean = rets.reduce((a, b) => a + b, 0) / rets.length;
    volatility = Math.sqrt(rets.reduce((a, r) => a + (r - mean) ** 2, 0) / rets.length) * 100;
  }

  // Max drawdown
  let maxDD = 0;
  let peak = 0;
  for (const p of prices) {
    if (p.close > peak) peak = p.close;
    const dd = (p.close - peak) / peak;
    if (dd < maxDD) maxDD = dd;
  }

  // Network health from taostats
  let netHealth = null;
  try {
    const netRes = await getDb().execute(
      "SELECT * FROM taostats_network_stats ORDER BY timestamp DESC LIMIT 1"
    );
    if (netRes.rows.length > 0) {
      netHealth = {
        total_subnets: Number(netRes.rows[0].total_subnets || 0),
        total_validators: Number(netRes.rows[0].total_validators || 0),
        total_miners: Number(netRes.rows[0].total_miners || 0),
        block_number: Number(netRes.rows[0].block_number || 0),
      };
    }
  } catch {}

  // Top movers (biggest 24h flow changes)
  let topMovers: { netuid: number; name: string; flow_24h: number }[] = [];
  try {
    const moversRes = await getDb().execute(`
      SELECT netuid, name, tao_flow_24h
      FROM taostats_subnets
      WHERE snapshot_ts = (SELECT MAX(snapshot_ts) FROM taostats_subnets)
        AND netuid != 0
      ORDER BY ABS(tao_flow_24h) DESC
      LIMIT 6
    `);
    topMovers = moversRes.rows.map((r) => ({
      netuid: Number(r.netuid),
      name: String(r.name || `SN${r.netuid}`),
      flow_24h: Number(r.tao_flow_24h || 0),
    }));
  } catch {}

  return { prices, apis, count, minTs, maxTs, current, change30d, volatility, maxDD, netHealth, topMovers };
}

export default async function OverviewPage() {
  const { prices, apis, count, minTs, maxTs, current, change30d, volatility, maxDD, netHealth, topMovers } = await getData();

  const minDate = minTs ? new Date(minTs * 1000).toLocaleDateString() : "N/A";
  const maxDate = maxTs ? new Date(maxTs * 1000).toLocaleDateString() : "N/A";

  return (
    <div className="space-y-6">
      <h1 className="text-2xl font-bold">Overview</h1>

      {/* Summary cards */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        <div className="card">
          <p className="text-xs text-[#8888a0]">Current Price</p>
          <p className="text-2xl font-bold mt-1">${current.toFixed(2)}</p>
        </div>
        <div className="card">
          <p className="text-xs text-[#8888a0]">30d Change</p>
          <p className={`text-2xl font-bold mt-1 ${change30d >= 0 ? "text-green-400" : "text-red-400"}`}>
            {change30d >= 0 ? "+" : ""}{change30d.toFixed(2)}%
          </p>
        </div>
        <div className="card">
          <p className="text-xs text-[#8888a0]">Volatility</p>
          <p className="text-2xl font-bold mt-1">{volatility.toFixed(2)}%</p>
        </div>
        <div className="card">
          <p className="text-xs text-[#8888a0]">Max Drawdown</p>
          <p className="text-2xl font-bold mt-1 text-red-400">{(maxDD * 100).toFixed(2)}%</p>
        </div>
      </div>

      {/* Network Health */}
      {netHealth && (
        <div className="card border-indigo-500/20">
          <h3 className="text-sm text-indigo-300 font-bold mb-3">Network Health</h3>
          <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
            <div>
              <p className="text-xs text-[#8888a0]">Active Subnets</p>
              <p className="text-xl font-bold mt-1">{netHealth.total_subnets}</p>
            </div>
            <div>
              <p className="text-xs text-[#8888a0]">Validators</p>
              <p className="text-xl font-bold mt-1">{netHealth.total_validators.toLocaleString()}</p>
            </div>
            <div>
              <p className="text-xs text-[#8888a0]">Miners</p>
              <p className="text-xl font-bold mt-1">{netHealth.total_miners.toLocaleString()}</p>
            </div>
            <div>
              <p className="text-xs text-[#8888a0]">Block</p>
              <p className="text-xl font-bold mt-1">{netHealth.block_number.toLocaleString()}</p>
            </div>
          </div>
        </div>
      )}

      {/* Top Movers */}
      {topMovers.length > 0 && (
        <div className="card">
          <h3 className="text-sm text-[#8888a0] mb-3">Top Movers (24h TAO Flow)</h3>
          <div className="grid grid-cols-2 md:grid-cols-3 gap-3">
            {topMovers.map((m) => (
              <div key={m.netuid} className="flex items-center justify-between p-3 rounded-lg bg-white/[0.02]">
                <div>
                  <span className="font-bold text-sm">SN{m.netuid}</span>
                  <span className="text-xs text-[#8888a0] ml-1.5 truncate">{m.name}</span>
                </div>
                <span className={`font-mono text-sm font-bold ${m.flow_24h >= 0 ? "text-green-400" : "text-red-400"}`}>
                  {fmtFlow(m.flow_24h)}
                </span>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Info row */}
      <div className="grid grid-cols-2 md:grid-cols-3 gap-4">
        <div className="card">
          <p className="text-xs text-[#8888a0]">Price Records</p>
          <p className="text-xl font-bold mt-1">{count.toLocaleString()}</p>
        </div>
        <div className="card">
          <p className="text-xs text-[#8888a0]">Date Range</p>
          <p className="text-sm font-medium mt-1">{minDate} — {maxDate}</p>
        </div>
        <div className="card">
          <p className="text-xs text-[#8888a0]">API Status</p>
          <div className="flex gap-2 mt-2 flex-wrap">
            {apis.map((a) => (
              <span
                key={a.name}
                className={`text-xs px-2 py-0.5 rounded-full ${
                  a.status === "ok" ? "bg-green-500/20 text-green-400" : "bg-red-500/20 text-red-400"
                }`}
              >
                {a.name}: {a.latency}ms
              </span>
            ))}
          </div>
        </div>
      </div>

      {/* Price chart */}
      <PriceChart data={prices} />
    </div>
  );
}
