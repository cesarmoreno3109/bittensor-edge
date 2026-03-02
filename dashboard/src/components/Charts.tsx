"use client";
import {
  LineChart, Line, XAxis, YAxis, Tooltip, ResponsiveContainer,
  BarChart, Bar, AreaChart, Area, CartesianGrid,
  ComposedChart, Legend,
} from "recharts";

const fmt = (v: number) => `$${v.toFixed(2)}`;
const fmtDate = (ts: number) => new Date(ts * 1000).toLocaleDateString("en-US", { month: "short", day: "numeric" });
const fmtShort = (v: number) => v >= 1e6 ? `${(v/1e6).toFixed(1)}M` : v >= 1e3 ? `${(v/1e3).toFixed(1)}K` : v.toFixed(1);

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
