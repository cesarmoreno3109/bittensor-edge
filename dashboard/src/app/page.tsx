import { db } from "@/lib/db";
import { PriceChart } from "@/components/Charts";

export const dynamic = "force-dynamic";

async function getData() {
  const [pricesRes, apiRes, countRes] = await Promise.all([
    db.execute("SELECT timestamp, open, high, low, close, volume FROM tao_prices ORDER BY timestamp"),
    db.execute("SELECT api_name, status, latency_ms, last_checked FROM api_status"),
    db.execute("SELECT COUNT(*) as cnt, MIN(timestamp) as min_ts, MAX(timestamp) as max_ts FROM tao_prices"),
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

  return { prices, apis, count, minTs, maxTs, current, change30d, volatility, maxDD };
}

export default async function OverviewPage() {
  const { prices, apis, count, minTs, maxTs, current, change30d, volatility, maxDD } = await getData();

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

      {/* Info row */}
      <div className="grid grid-cols-2 md:grid-cols-3 gap-4">
        <div className="card">
          <p className="text-xs text-[#8888a0]">Total Records</p>
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
