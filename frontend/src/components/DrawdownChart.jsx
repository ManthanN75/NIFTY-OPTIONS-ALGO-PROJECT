import { Area, AreaChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { formatPercent, formatShortDate } from "../format";

// How far below the highest-balance-so-far we are, at every point in
// time (always <= 0). Makes the "pain" of a strategy visible even when
// the equity curve above looks fine overall.
export default function DrawdownChart({ data }) {
  if (!data || data.length === 0) {
    return <div className="chart-empty">No trades to plot yet.</div>;
  }

  return (
    <ResponsiveContainer width="100%" height={200}>
      <AreaChart data={data} margin={{ top: 10, right: 20, left: 10, bottom: 0 }}>
        <CartesianGrid stroke="var(--border)" strokeDasharray="3 3" />
        <XAxis dataKey="date" tickFormatter={formatShortDate} stroke="var(--text-muted)" fontSize={12} />
        <YAxis stroke="var(--text-muted)" fontSize={12} tickFormatter={(value) => `${value}%`} width={50} />
        <Tooltip
          contentStyle={{ background: "var(--bg-panel)", border: "1px solid var(--border)", borderRadius: 8 }}
          labelFormatter={formatShortDate}
          formatter={(value) => [formatPercent(value), "Drawdown"]}
        />
        <Area type="monotone" dataKey="drawdownPct" stroke="var(--red)" fill="var(--red)" fillOpacity={0.25} />
      </AreaChart>
    </ResponsiveContainer>
  );
}
