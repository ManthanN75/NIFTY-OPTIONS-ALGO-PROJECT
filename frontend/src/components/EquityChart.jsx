import { CartesianGrid, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { formatRupees, formatShortDate } from "../format";

// The account balance over time, trade by trade. Should trend up and to
// the right for a strategy that's working.
export default function EquityChart({ data }) {
  if (!data || data.length === 0) {
    return <div className="chart-empty">No trades to plot yet.</div>;
  }

  return (
    <ResponsiveContainer width="100%" height={280}>
      <LineChart data={data} margin={{ top: 10, right: 20, left: 10, bottom: 0 }}>
        <CartesianGrid stroke="var(--border)" strokeDasharray="3 3" />
        <XAxis dataKey="date" tickFormatter={formatShortDate} stroke="var(--text-muted)" fontSize={12} />
        <YAxis
          stroke="var(--text-muted)"
          fontSize={12}
          tickFormatter={(value) => `${(value / 1000).toFixed(0)}k`}
          width={50}
        />
        <Tooltip
          contentStyle={{ background: "var(--bg-panel)", border: "1px solid var(--border)", borderRadius: 8 }}
          labelFormatter={formatShortDate}
          formatter={(value) => [formatRupees(value), "Balance"]}
        />
        <Line type="monotone" dataKey="balance" stroke="var(--accent)" strokeWidth={2} dot={{ r: 3 }} />
      </LineChart>
    </ResponsiveContainer>
  );
}
