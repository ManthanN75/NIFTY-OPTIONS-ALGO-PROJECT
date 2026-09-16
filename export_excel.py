"""
Exports backtest results to a single Excel workbook (.xlsx) instead of
separate CSVs -- one file, multiple tabs, formatted to be handed straight
to a recruiter (bold headers, real % / Rs number formatting, frozen
header row, sensible column widths) rather than a raw data dump.

Results are expressed as percentages where that's the natural unit -- not
everything is a percent: Sharpe ratio and profit factor are ratios, not
percentages, so they're left as plain numbers and labeled clearly instead
of being forced into a "%" that wouldn't mean anything.

Produces 3 sheets:
  - "Summary"      -- the key metrics, one per row, each formatted for its unit
  - "Trade Log"     -- every trade, with a per-trade return % column added
  - "Equity Curve"  -- account balance over time, with a cumulative
                       return % column added
"""

from __future__ import annotations

import pandas as pd
from openpyxl.styles import Alignment, Font, PatternFill

HEADER_FILL = PatternFill(start_color="1F2937", end_color="1F2937", fill_type="solid")
HEADER_FONT = Font(bold=True, color="FFFFFF")

# NOTE: our *_pct values are already stored as plain percentage numbers
# (e.g. 12.23 meaning "12.23%"), not fractions (0.1223). Excel's built-in
# "0.00%" format expects a fraction and would multiply by 100 again (showing
# "1223.00%"), so we use a custom format that just appends a literal "%"
# without rescaling the stored number.
PCT_FORMAT = '0.00"%"'
MONEY_FORMAT = '"Rs" #,##0.00'
RATIO_FORMAT = "0.00"
INT_FORMAT = "0"


def build_summary_rows(metrics: dict) -> list[tuple]:
    """Returns (label, value, number_format) triples for the Summary sheet."""
    sharpe = metrics["sharpe"]
    win_rate = metrics["win_rate_pct"]
    profit_factor = metrics["profit_factor"]

    return [
        ("Number of Trades", metrics["num_trades"], INT_FORMAT),
        ("Total Return", round(metrics["total_return_pct"], 2), PCT_FORMAT),
        ("Win Rate", round(win_rate, 2) if win_rate == win_rate else None, PCT_FORMAT),
        ("Max Drawdown", round(metrics["max_drawdown_pct"], 2), PCT_FORMAT),
        ("Sharpe Ratio (per-trade, not annualized)",
         round(sharpe, 2) if sharpe == sharpe else None, RATIO_FORMAT),
        ("Profit Factor (ratio, not a %)",
         round(profit_factor, 2) if profit_factor not in (float("inf"),) else "No losing trades (undefined)",
         RATIO_FORMAT),
        ("Final Balance", round(metrics["final_balance"], 2), MONEY_FORMAT),
    ]


def build_trade_log_sheet(trade_log: pd.DataFrame, starting_balance: float) -> pd.DataFrame:
    if trade_log.empty:
        return trade_log
    sheet = trade_log.copy()
    # Per-trade return, as a % of starting capital -- easier to compare
    # trades of different sizes than the raw rupee P&L alone.
    sheet["return_pct"] = (sheet["pnl_rupees"] / starting_balance * 100).round(2)
    sheet["cumulative_return_pct"] = ((sheet["balance_after"] - starting_balance) / starting_balance * 100).round(2)
    return sheet


def build_equity_curve_sheet(equity: pd.Series, starting_balance: float) -> pd.DataFrame:
    sheet = equity.reset_index()
    sheet.columns = ["date", "balance"]
    sheet["cumulative_return_pct"] = ((sheet["balance"] - starting_balance) / starting_balance * 100).round(2)
    return sheet


def _style_header_row(worksheet, num_columns: int) -> None:
    for col_idx in range(1, num_columns + 1):
        cell = worksheet.cell(row=1, column=col_idx)
        cell.fill = HEADER_FILL
        cell.font = HEADER_FONT
        cell.alignment = Alignment(horizontal="center")
    worksheet.freeze_panes = "A2"


def _autofit_columns(worksheet, df: pd.DataFrame) -> None:
    for i, col in enumerate(df.columns, start=1):
        content_width = df[col].astype(str).map(len).max() if len(df) else 10
        width = max(12, min(34, content_width, len(str(col)) + 2))
        worksheet.column_dimensions[worksheet.cell(row=1, column=i).column_letter].width = width


def export_results_to_excel(trade_log: pd.DataFrame, metrics: dict, equity: pd.Series,
                             starting_balance: float, output_path: str) -> None:
    summary_rows = build_summary_rows(metrics)
    summary_sheet = pd.DataFrame([(label, value) for label, value, _ in summary_rows],
                                  columns=["Metric", "Value"])
    trade_sheet = build_trade_log_sheet(trade_log, starting_balance)
    equity_sheet = build_equity_curve_sheet(equity, starting_balance)

    with pd.ExcelWriter(output_path, engine="openpyxl") as writer:
        summary_sheet.to_excel(writer, sheet_name="Summary", index=False)
        trade_sheet.to_excel(writer, sheet_name="Trade Log", index=False)
        equity_sheet.to_excel(writer, sheet_name="Equity Curve", index=False)

        # --- Summary: apply the right number format to each metric's Value cell ---
        summary_ws = writer.sheets["Summary"]
        for row_idx, (_, _, number_format) in enumerate(summary_rows, start=2):  # row 1 is the header
            summary_ws.cell(row=row_idx, column=2).number_format = number_format

        # --- Trade Log: money columns as Rs, % columns as % ---
        trade_ws = writer.sheets["Trade Log"]
        if not trade_sheet.empty:
            money_cols = {"premium_collected_rupees", "pnl_rupees", "balance_after"}
            pct_cols = {"return_pct", "cumulative_return_pct"}
            for col_idx, col in enumerate(trade_sheet.columns, start=1):
                fmt = MONEY_FORMAT if col in money_cols else PCT_FORMAT if col in pct_cols else None
                if fmt:
                    for row_idx in range(2, len(trade_sheet) + 2):
                        trade_ws.cell(row=row_idx, column=col_idx).number_format = fmt

        # --- Equity Curve: balance as Rs, cumulative return as % ---
        equity_ws = writer.sheets["Equity Curve"]
        for col_idx, col in enumerate(equity_sheet.columns, start=1):
            fmt = MONEY_FORMAT if col == "balance" else PCT_FORMAT if col == "cumulative_return_pct" else None
            if fmt:
                for row_idx in range(2, len(equity_sheet) + 2):
                    equity_ws.cell(row=row_idx, column=col_idx).number_format = fmt

        # --- Header styling + column widths on every sheet ---
        for sheet_name, df in [("Summary", summary_sheet), ("Trade Log", trade_sheet), ("Equity Curve", equity_sheet)]:
            ws = writer.sheets[sheet_name]
            _style_header_row(ws, len(df.columns) if len(df.columns) else 2)
            _autofit_columns(ws, df)

    print(f"Saved {output_path}")
