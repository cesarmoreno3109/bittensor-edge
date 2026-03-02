import { getDb } from "@/lib/db";
import { EquityCurveChart, DrawdownChart } from "@/components/Charts";

export const dynamic = "force-dynamic";

async function getData() {
  // For now, show latest price data formatted as basic equity curve
  // A real implementation would store backtest results in DB
  const res = await getDb().execute("SELECT timestamp, close FROM tao_prices ORDER BY timestamp");

  if (res.rows.length === 0) return { equity: [], drawdown: [], trades: [], stats: null };

  const prices = res.rows.map((r) => ({
    ts: Number(r.timestamp),
    close: Number(r.close),
  }));

  // Simulate a basic mean-reversion backtest for display
  const lookback = 24;
  const entryZ = 2.0;
  const exitZ = 0.5;

  // Compute z-scores
  const closes = prices.map((p) => p.close);
  const signals: number[] = new Array(closes.length).fill(0);

  for (let i = lookback; i < closes.length; i++) {
    const window = closes.slice(i - lookback, i);
    const mean = window.reduce((a, b) => a + b, 0) / window.length;
    const std = Math.sqrt(window.reduce((a, v) => a + (v - mean) ** 2, 0) / window.length);
    if (std === 0) continue;
    const z = (closes[i] - mean) / std;

    if (z < -entryZ) signals[i] = 1;
    else if (z > entryZ) signals[i] = -1;
    else if (Math.abs(z) < exitZ) signals[i] = 0;
    else signals[i] = signals[i - 1] || 0;
  }

  // Generate equity curve and trades
  let equity = 1.0;
  const equityData: { time: string; equity: number }[] = [];
  const trades: { entry: string; exit: string; direction: string; pnl: number }[] = [];
  let pos = 0;
  let entryPrice = 0;
  let entryTime = "";
  const slippage = 0.003;
  const fee = 0.001;

  for (let i = 0; i < prices.length; i++) {
    const time = new Date(prices[i].ts * 1000).toLocaleDateString("en-US", { month: "short", day: "numeric" });
    const price = prices[i].close;
    const sig = signals[i];

    if (pos !== 0 && sig !== pos) {
      const raw = pos === 1
        ? (price - entryPrice) / entryPrice
        : (entryPrice - price) / entryPrice;
      const pnl = raw - 2 * (slippage + fee);
      equity *= (1 + pnl);
      trades.push({
        entry: entryTime,
        exit: time,
        direction: pos === 1 ? "Long" : "Short",
        pnl,
      });
      pos = 0;
    }
    if (pos === 0 && sig !== 0) {
      pos = sig;
      entryPrice = price;
      entryTime = time;
    }
    equityData.push({ time, equity: parseFloat(equity.toFixed(4)) });
  }

  // Drawdown
  let peak = 0;
  const drawdownData = equityData.map((e) => {
    if (e.equity > peak) peak = e.equity;
    return { time: e.time, drawdown: peak > 0 ? (e.equity - peak) / peak : 0 };
  });

  // Stats
  const totalPnl = equity - 1;
  const winTrades = trades.filter((t) => t.pnl > 0).length;
  const winRate = trades.length > 0 ? winTrades / trades.length : 0;
  const maxDD = Math.min(...drawdownData.map((d) => d.drawdown));
  const pnls = trades.map((t) => t.pnl);
  const mean = pnls.length > 0 ? pnls.reduce((a, b) => a + b, 0) / pnls.length : 0;
  const std = pnls.length > 1
    ? Math.sqrt(pnls.reduce((a, p) => a + (p - mean) ** 2, 0) / (pnls.length - 1))
    : 0;
  const sharpe = std > 0 ? (mean / std) * Math.sqrt(365) : 0;

  return {
    equity: equityData,
    drawdown: drawdownData,
    trades,
    stats: { totalPnl, winRate, maxDD, sharpe, numTrades: trades.length },
  };
}

export default async function BacktestPage() {
  const { equity, drawdown, trades, stats } = await getData();

  return (
    <div className="space-y-6">
      <h1 className="text-2xl font-bold">Backtest Results</h1>
      <p className="text-sm text-[#8888a0]">Mean Reversion (lookback=24h, entry_z=2.0, exit_z=0.5)</p>

      {stats ? (
        <>
          {/* Performance cards */}
          <div className="grid grid-cols-2 md:grid-cols-5 gap-4">
            <div className="card">
              <p className="text-xs text-[#8888a0]">Total P&L</p>
              <p className={`text-xl font-bold mt-1 ${stats.totalPnl >= 0 ? "text-green-400" : "text-red-400"}`}>
                {(stats.totalPnl * 100).toFixed(2)}%
              </p>
            </div>
            <div className="card">
              <p className="text-xs text-[#8888a0]">Sharpe</p>
              <p className="text-xl font-bold mt-1">{stats.sharpe.toFixed(2)}</p>
            </div>
            <div className="card">
              <p className="text-xs text-[#8888a0]">Win Rate</p>
              <p className="text-xl font-bold mt-1">{(stats.winRate * 100).toFixed(1)}%</p>
            </div>
            <div className="card">
              <p className="text-xs text-[#8888a0]">Max Drawdown</p>
              <p className="text-xl font-bold mt-1 text-red-400">{(stats.maxDD * 100).toFixed(2)}%</p>
            </div>
            <div className="card">
              <p className="text-xs text-[#8888a0]">Trades</p>
              <p className="text-xl font-bold mt-1">{stats.numTrades}</p>
            </div>
          </div>

          {/* Charts */}
          <EquityCurveChart data={equity} />
          <DrawdownChart data={drawdown} />

          {/* Trade log */}
          <div className="card overflow-x-auto">
            <h3 className="text-sm text-[#8888a0] mb-3">Trade Log</h3>
            <table className="w-full text-sm">
              <thead>
                <tr className="text-left text-[#8888a0] border-b border-[#1e1e2e]">
                  <th className="pb-2 pr-4">#</th>
                  <th className="pb-2 pr-4">Entry</th>
                  <th className="pb-2 pr-4">Exit</th>
                  <th className="pb-2 pr-4">Direction</th>
                  <th className="pb-2">P&L</th>
                </tr>
              </thead>
              <tbody>
                {trades.map((t, i) => (
                  <tr key={i} className="border-b border-[#1e1e2e]/50 hover:bg-white/5">
                    <td className="py-1.5 pr-4 text-[#8888a0]">{i + 1}</td>
                    <td className="py-1.5 pr-4">{t.entry}</td>
                    <td className="py-1.5 pr-4">{t.exit}</td>
                    <td className="py-1.5 pr-4">
                      <span className={`text-xs px-2 py-0.5 rounded-full ${
                        t.direction === "Long" ? "bg-green-500/20 text-green-400" : "bg-red-500/20 text-red-400"
                      }`}>
                        {t.direction}
                      </span>
                    </td>
                    <td className={`py-1.5 font-mono ${t.pnl >= 0 ? "text-green-400" : "text-red-400"}`}>
                      {(t.pnl * 100).toFixed(3)}%
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      ) : (
        <div className="card text-center py-12 text-[#8888a0]">
          No data available. Run pipeline scripts first.
        </div>
      )}
    </div>
  );
}
