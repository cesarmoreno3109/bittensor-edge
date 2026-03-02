"use client";
import {
  LineChart, Line, XAxis, YAxis, Tooltip, ResponsiveContainer,
  BarChart, Bar, AreaChart, Area, CartesianGrid,
  ComposedChart, Legend, Cell, ScatterChart, Scatter, ZAxis,
} from "recharts";

const fmt = (v: number) => `$${v.toFixed(2)}`;
const fmtDate = (ts: number) => new Date(ts * 1000).toLocaleDateString("en-US", { month: "short", day: "numeric" });
const fmtShort = (v: number) => v >= 1e6 ? `${(v/1e6).toFixed(1)}M` : v >= 1e3 ? `${(v/1e3).toFixed(1)}K` : v <= -1e6 ? `${(v/1e6).toFixed(1)}M` : v <= -1e3 ? `${(v/1e3).toFixed(1)}K` : v.toFixed(1);
const fmtTAO = (v: number) => `${v >= 0 ? "+" : ""}${fmtShort(v)} TAO`;

export function PriceChart({ data }: { data: { timestamp: number; close: number; volume?: number }[] }) {
  return (
    <div className="card">
      <h3 className="text-sm text-[#8888a0] mb-3">TAO/USD Price (30d)</h3>
      <ResponsiveContainer width="100%" height={300}>
        <ComposedChart data={data}>
          <CartesianGrid strokeDasharray="3 3" stroke="#1e1e2e" />
          <XAxis dataKey="timestamp" tickFormatter={fmtDate} stroke="#555" fontSize={11} />
          <YAxis yAxisId="price" tickFormatter={fmt} stroke="#555" fontSize={11} />
          <YAxis yAxisId="vol" orientation="right" tickFormatter={fmtShort} stroke="#555" fontSize={11} />
          <Tooltip
            contentStyle={{ background: "#12121a", border: "1px solid #1e1e2e", borderRadius: 8 }}
            labelFormatter={(v) => new Date(Number(v) * 1000).toLocaleString()}
            formatter={(v: number, name: string) => [name === "close" ? fmt(v) : fmtShort(v), name === "close" ? "Price" : "Volume"]}
          />
          <Bar yAxisId="vol" dataKey="volume" fill="#6366f120" radius={[2, 2, 0, 0]} />
          <Line yAxisId="price" dataKey="close" stroke="#6366f1" strokeWidth={2} dot={false} />
        </ComposedChart>
      </ResponsiveContainer>
    </div>
  );
}

export function StakeFlowChart({ data }: { data: { date: string; net_flow: number }[] }) {
  return (
    <div className="card">
      <h3 className="text-sm text-[#8888a0] mb-3">Net Stake Flow</h3>
      <ResponsiveContainer width="100%" height={250}>
        <BarChart data={data}>
          <CartesianGrid strokeDasharray="3 3" stroke="#1e1e2e" />
          <XAxis dataKey="date" stroke="#555" fontSize={11} />
          <YAxis tickFormatter={fmtShort} stroke="#555" fontSize={11} />
          <Tooltip contentStyle={{ background: "#12121a", border: "1px solid #1e1e2e", borderRadius: 8 }} />
          <Bar dataKey="net_flow" fill="#6366f1" radius={[3, 3, 0, 0]} />
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}

export function EmissionChart({ data }: { data: { subnet_id: number; emission_rate: number }[] }) {
  return (
    <div className="card">
      <h3 className="text-sm text-[#8888a0] mb-3">Subnet Emission Distribution</h3>
      <ResponsiveContainer width="100%" height={250}>
        <BarChart data={data}>
          <CartesianGrid strokeDasharray="3 3" stroke="#1e1e2e" />
          <XAxis dataKey="subnet_id" stroke="#555" fontSize={11} label={{ value: "Subnet", position: "insideBottom", offset: -2, fontSize: 11, fill: "#555" }} />
          <YAxis stroke="#555" fontSize={11} />
          <Tooltip contentStyle={{ background: "#12121a", border: "1px solid #1e1e2e", borderRadius: 8 }} />
          <Bar dataKey="emission_rate" fill="#22c55e" radius={[3, 3, 0, 0]} />
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}

export function EquityCurveChart({ data }: { data: { time: string; equity: number }[] }) {
  return (
    <div className="card">
      <h3 className="text-sm text-[#8888a0] mb-3">Equity Curve</h3>
      <ResponsiveContainer width="100%" height={300}>
        <LineChart data={data}>
          <CartesianGrid strokeDasharray="3 3" stroke="#1e1e2e" />
          <XAxis dataKey="time" stroke="#555" fontSize={11} />
          <YAxis stroke="#555" fontSize={11} domain={["auto", "auto"]} />
          <Tooltip contentStyle={{ background: "#12121a", border: "1px solid #1e1e2e", borderRadius: 8 }} />
          <Line dataKey="equity" stroke="#22c55e" strokeWidth={2} dot={false} />
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}

export function DrawdownChart({ data }: { data: { time: string; drawdown: number }[] }) {
  return (
    <div className="card">
      <h3 className="text-sm text-[#8888a0] mb-3">Drawdown</h3>
      <ResponsiveContainer width="100%" height={200}>
        <AreaChart data={data}>
          <CartesianGrid strokeDasharray="3 3" stroke="#1e1e2e" />
          <XAxis dataKey="time" stroke="#555" fontSize={11} />
          <YAxis stroke="#555" fontSize={11} tickFormatter={(v) => `${(v * 100).toFixed(1)}%`} />
          <Tooltip contentStyle={{ background: "#12121a", border: "1px solid #1e1e2e", borderRadius: 8 }} formatter={(v: number) => `${(v * 100).toFixed(2)}%`} />
          <Area dataKey="drawdown" stroke="#ef4444" fill="#ef444420" />
        </AreaChart>
      </ResponsiveContainer>
    </div>
  );
}

// ── Subnet Charts ────────────────────────────────────────────────────────────

export function SubnetFlowChart({ data }: { data: { netuid: number; name: string; flow_30d: number; flow_7d: number }[] }) {
  return (
    <div className="card">
      <h3 className="text-sm text-[#8888a0] mb-3">TAO Flow by Subnet (Top 20)</h3>
      <ResponsiveContainer width="100%" height={400}>
        <BarChart data={data.slice(0, 20)} layout="vertical">
          <CartesianGrid strokeDasharray="3 3" stroke="#1e1e2e" />
          <XAxis type="number" tickFormatter={fmtShort} stroke="#555" fontSize={11} />
          <YAxis type="category" dataKey="name" width={100} stroke="#555" fontSize={10} />
          <Tooltip
            contentStyle={{ background: "#12121a", border: "1px solid #1e1e2e", borderRadius: 8 }}
            formatter={(v: number) => fmtTAO(v)}
          />
          <Legend />
          <Bar dataKey="flow_30d" fill="#6366f1" name="30d Flow" radius={[0, 3, 3, 0]} />
          <Bar dataKey="flow_7d" fill="#22c55e" name="7d Flow" radius={[0, 3, 3, 0]} />
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}

export function SubnetScoreChart({ data }: { data: { netuid: number; name: string; score: number; risk: string }[] }) {
  return (
    <div className="card">
      <h3 className="text-sm text-[#8888a0] mb-3">Subnet Composite Scores</h3>
      <ResponsiveContainer width="100%" height={350}>
        <BarChart data={data.slice(0, 20)}>
          <CartesianGrid strokeDasharray="3 3" stroke="#1e1e2e" />
          <XAxis dataKey="name" stroke="#555" fontSize={10} angle={-45} textAnchor="end" height={80} />
          <YAxis stroke="#555" fontSize={11} domain={[0, 10]} />
          <Tooltip contentStyle={{ background: "#12121a", border: "1px solid #1e1e2e", borderRadius: 8 }} />
          <Bar dataKey="score" radius={[3, 3, 0, 0]}>
            {data.slice(0, 20).map((d, i) => (
              <Cell key={i} fill={d.risk === "LOW" ? "#22c55e" : d.risk === "MEDIUM" ? "#eab308" : "#ef4444"} />
            ))}
          </Bar>
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}

export function EmissionVsFlowScatter({ data }: { data: { netuid: number; name: string; emission: number; flow: number; score: number }[] }) {
  return (
    <div className="card">
      <h3 className="text-sm text-[#8888a0] mb-3">Emission vs TAO Flow (30d)</h3>
      <ResponsiveContainer width="100%" height={300}>
        <ScatterChart>
          <CartesianGrid strokeDasharray="3 3" stroke="#1e1e2e" />
          <XAxis dataKey="emission" name="Emission %" stroke="#555" fontSize={11} />
          <YAxis dataKey="flow" name="30d Flow (TAO)" tickFormatter={fmtShort} stroke="#555" fontSize={11} />
          <ZAxis dataKey="score" range={[30, 200]} name="Score" />
          <Tooltip
            contentStyle={{ background: "#12121a", border: "1px solid #1e1e2e", borderRadius: 8 }}
            formatter={(v: number, name: string) => [name === "30d Flow (TAO)" ? fmtTAO(v) : v.toFixed(4), name]}
          />
          <Scatter data={data} fill="#6366f1" />
        </ScatterChart>
      </ResponsiveContainer>
    </div>
  );
}
