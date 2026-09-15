// Small formatting + math helpers shared by the components.
// Keeping them here (instead of copy-pasted in each component) means
// there's exactly one place to fix a formatting bug.

/** Rupees, e.g. 542844 -> "Rs 5,42,844" (Indian-style comma grouping). */
export function formatRupees(value) {
  if (value === null || value === undefined || Number.isNaN(value)) return "-";
  return "Rs " + Math.round(value).toLocaleString("en-IN");
}

/** A plain number, e.g. Sharpe ratio: 0.89 -> "0.89". */
export function formatNumber(value, digits = 2) {
  if (value === null || value === undefined || Number.isNaN(value)) return "-";
  if (!Number.isFinite(value)) return "∞"; // "∞" -- shown when profit factor has no losing trades to divide by
  return value.toFixed(digits);
}

/** A percentage, e.g. 12.233 -> "12.23%". */
export function formatPercent(value, digits = 2) {
  if (value === null || value === undefined || Number.isNaN(value)) return "-";
  return `${value.toFixed(digits)}%`;
}

/** Short date for chart axes/table cells, e.g. "2026-04-23" -> "23 Apr". */
export function formatShortDate(isoDate) {
  const date = new Date(isoDate);
  return date.toLocaleDateString("en-IN", { day: "2-digit", month: "short" });
}

/**
 * Turn an equity curve ([{date, balance}, ...]) into a drawdown series
 * ([{date, drawdownPct}, ...]): at every point, how far below the highest
 * balance-so-far we are, as a percentage. Always <= 0.
 *
 * This mirrors the exact same formula used on the backend
 * (performance_report.py's compute_drawdown_series) -- we recompute it
 * here instead of adding another API call, since it's cheap and the
 * equity curve is already on the page.
 */
export function computeDrawdownSeries(equityCurve) {
  let runningPeak = -Infinity;
  return equityCurve.map((point) => {
    runningPeak = Math.max(runningPeak, point.balance);
    const drawdownPct = ((point.balance - runningPeak) / runningPeak) * 100;
    return { date: point.date, drawdownPct };
  });
}
