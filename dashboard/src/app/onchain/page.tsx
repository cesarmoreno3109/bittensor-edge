import { db } from "@/lib/db";
import { StakeFlowChart, EmissionChart } from "@/components/Charts";

export const dynamic = "force-dynamic";

async function getData() {
  const [eventsRes, emissionRes, flowRes] = await Promise.all([
    db.execute("SELECT block_num, timestamp, event_type, subnet_id, amount, hotkey FROM staking_events ORDER BY timestamp DESC LIMIT 200"),
    db.execute("SELECT subnet_id, emission_rate FROM subnet_info WHERE snapshot_ts = (SELECT MAX(snapshot_ts) FROM subnet_info) AND emission_rate IS NOT NULL ORDER BY subnet_id"),
    db.execute(`
      SELECT DATE(timestamp, 'unixepoch') as date,
        SUM(CASE WHEN event_type='StakeAdded' THEN amount ELSE 0 END) -
        SUM(CASE WHEN event_type='StakeRemoved' THEN amount ELSE 0 END) as net_flow
      FROM staking_events
      WHERE amount IS NOT NULL
      GROUP BY date ORDER BY date
    `),
  ]);

  const events = eventsRes.rows.map((r) => ({
    block: Number(r.block_num),
    timestamp: Number(r.timestamp),
    type: String(r.event_type),
    subnet: r.subnet_id != null ? Number(r.subnet_id) : null,
    amount: r.amount != null ? Number(r.amount) : null,
    hotkey: String(r.hotkey || "").slice(0, 12) + "...",
  }));

  const emissions = emissionRes.rows.map((r) => ({
    subnet_id: Number(r.subnet_id),
    emission_rate: Number(r.emission_rate),
  }));

  const flow = flowRes.rows.map((r) => ({
    date: String(r.date),
    net_flow: Number(r.net_flow || 0),
  }));

  // Event type breakdown
  const breakdown: Record<string, number> = {};
  for (const e of events) {
    breakdown[e.type] = (breakdown[e.type] || 0) + 1;
  }

  return { events, emissions, flow, breakdown };
}

export default async function OnchainPage() {
  const { events, emissions, flow, breakdown } = await getData();

  return (
    <div className="space-y-6">
      <h1 className="text-2xl font-bold">On-Chain Data</h1>

      {/* Event type badges */}
      <div className="flex gap-3 flex-wrap">
        {Object.entries(breakdown).map(([type, count]) => (
          <span key={type} className="card text-sm">
            <span className="text-[#8888a0]">{type}:</span> <span className="font-bold">{count}</span>
          </span>
        ))}
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <StakeFlowChart data={flow} />
        <EmissionChart data={emissions} />
      </div>

      {/* Events table */}
      <div className="card overflow-x-auto">
        <h3 className="text-sm text-[#8888a0] mb-3">Recent Staking Events</h3>
        <table className="w-full text-sm">
          <thead>
            <tr className="text-left text-[#8888a0] border-b border-[#1e1e2e]">
              <th className="pb-2 pr-4">Block</th>
              <th className="pb-2 pr-4">Time</th>
              <th className="pb-2 pr-4">Type</th>
              <th className="pb-2 pr-4">Subnet</th>
              <th className="pb-2 pr-4">Amount</th>
              <th className="pb-2">Hotkey</th>
            </tr>
          </thead>
          <tbody>
            {events.slice(0, 50).map((e) => (
              <tr key={e.block} className="border-b border-[#1e1e2e]/50 hover:bg-white/5">
                <td className="py-1.5 pr-4 font-mono text-xs">{e.block}</td>
                <td className="py-1.5 pr-4 text-xs">{new Date(e.timestamp * 1000).toLocaleString()}</td>
                <td className="py-1.5 pr-4">
                  <span className={`text-xs px-2 py-0.5 rounded-full ${
                    e.type === "StakeAdded" ? "bg-green-500/20 text-green-400" :
                    e.type === "StakeRemoved" ? "bg-red-500/20 text-red-400" :
                    "bg-blue-500/20 text-blue-400"
                  }`}>
                    {e.type}
                  </span>
                </td>
                <td className="py-1.5 pr-4">{e.subnet ?? "—"}</td>
                <td className="py-1.5 pr-4 font-mono">{e.amount != null ? e.amount.toFixed(4) : "—"}</td>
                <td className="py-1.5 font-mono text-xs text-[#8888a0]">{e.hotkey}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
