import MetricCard from "./MetricCard";
import { formatNumber, formatPercent, formatRupees } from "../format";

// Shows one period's (tuning or test) headline number (total return) plus
// the 4 key metric cards. Used twice, side by side, in App.jsx -- once
// for tuning, once for test -- so a viewer can compare them at a glance.
export default function PeriodMetricsColumn({ title, subtitle, metrics }) {
  const { total_return_pct, sharpe, win_rate_pct, max_drawdown_pct, profit_factor, num_trades } = metrics;

  return (
    <div className="period-column">
      <div className="period-header">
        <h2>{title}</h2>
        <span className="period-subtitle">{subtitle}</span>
      </div>

      <div className={`total-return tone-${total_return_pct >= 0 ? "good" : "bad"}`}>
        {formatPercent(total_return_pct)}
        <span className="total-return-label">total return &middot; {num_trades} trades</span>
      </div>

      <div className="metric-grid">
        <MetricCard label="Sharpe Ratio" value={formatNumber(sharpe)} tone={sharpe >= 0 ? "good" : "bad"} />
        <MetricCard label="Win Rate" value={formatPercent(win_rate_pct, 1)} tone={win_rate_pct >= 50 ? "good" : "bad"} />
        <MetricCard label="Max Drawdown" value={formatPercent(max_drawdown_pct)} tone="bad" />
        <MetricCard label="Profit Factor" value={formatNumber(profit_factor)} tone={profit_factor >= 1 ? "good" : "bad"} />
      </div>
    </div>
  );
}
