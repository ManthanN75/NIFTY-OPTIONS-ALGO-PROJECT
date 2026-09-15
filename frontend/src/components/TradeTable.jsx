import { useMemo, useState } from "react";
import { formatRupees } from "../format";

// The columns shown in the table, in order. `key` must match a field
// name in the trade records coming from the API. Add/remove/reorder
// columns here -- nothing else needs to change.
const COLUMNS = [
  { key: "entry_date", label: "Entry" },
  { key: "exit_date", label: "Exit" },
  { key: "expiry", label: "Expiry" },
  { key: "short_call_strike", label: "Short CE" },
  { key: "short_put_strike", label: "Short PE" },
  { key: "long_call_strike", label: "Long CE" },
  { key: "long_put_strike", label: "Long PE" },
  { key: "premium_collected_rupees", label: "Premium", isMoney: true },
  { key: "pnl_rupees", label: "P&L", isMoney: true },
  { key: "exit_reason", label: "Exit Reason" },
];

/** A searchable, sortable table of trades. Click a column header to sort
 * by it (click again to flip direction). Type in the search box to filter
 * across every column at once (e.g. type "stop_loss" to see only stopped-out trades). */
export default function TradeTable({ trades }) {
  const [searchTerm, setSearchTerm] = useState("");
  const [sortKey, setSortKey] = useState("exit_date");
  const [sortDir, setSortDir] = useState("asc"); // "asc" | "desc"

  const visibleRows = useMemo(() => {
    const term = searchTerm.trim().toLowerCase();
    const filtered = term
      ? trades.filter((row) =>
          COLUMNS.some((col) => String(row[col.key]).toLowerCase().includes(term))
        )
      : trades;

    const sorted = [...filtered].sort((a, b) => {
      const aVal = a[sortKey];
      const bVal = b[sortKey];
      if (aVal === bVal) return 0;
      const result = aVal > bVal ? 1 : -1;
      return sortDir === "asc" ? result : -result;
    });

    return sorted;
  }, [trades, searchTerm, sortKey, sortDir]);

  function handleSort(key) {
    if (key === sortKey) {
      setSortDir((dir) => (dir === "asc" ? "desc" : "asc"));
    } else {
      setSortKey(key);
      setSortDir("asc");
    }
  }

  return (
    <div className="trade-table-wrapper">
      <input
        className="trade-search"
        type="text"
        placeholder="Search trades (e.g. profit_target, 23800...)"
        value={searchTerm}
        onChange={(event) => setSearchTerm(event.target.value)}
      />

      <div className="trade-table-scroll">
        <table className="trade-table">
          <thead>
            <tr>
              {COLUMNS.map((col) => (
                <th key={col.key} onClick={() => handleSort(col.key)}>
                  {col.label}
                  {sortKey === col.key && <span className="sort-arrow">{sortDir === "asc" ? " ▲" : " ▼"}</span>}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {visibleRows.length === 0 && (
              <tr>
                <td colSpan={COLUMNS.length} className="trade-table-empty">
                  No trades match "{searchTerm}".
                </td>
              </tr>
            )}
            {visibleRows.map((row, index) => (
              <tr key={`${row.entry_date}-${index}`}>
                {COLUMNS.map((col) => {
                  const value = row[col.key];
                  if (col.isMoney) {
                    return (
                      <td key={col.key} className={value >= 0 ? "tone-good" : "tone-bad"}>
                        {formatRupees(value)}
                      </td>
                    );
                  }
                  return <td key={col.key}>{value}</td>;
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
