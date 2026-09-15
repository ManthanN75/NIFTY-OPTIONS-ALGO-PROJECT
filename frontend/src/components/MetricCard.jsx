// One small card showing a single number (e.g. "Sharpe Ratio: 0.89").
// `tone` optionally colors the value green/red so good/bad numbers are
// visible at a glance -- pass "good" or "bad", or leave it unset for a
// neutral color.
export default function MetricCard({ label, value, tone = "neutral" }) {
  return (
    <div className="metric-card">
      <div className="metric-card-label">{label}</div>
      <div className={`metric-card-value tone-${tone}`}>{value}</div>
    </div>
  );
}
