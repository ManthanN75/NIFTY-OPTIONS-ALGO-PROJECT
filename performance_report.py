"""
PERFORMANCE METRICS + CHARTS: turn any trade log into a scorecard.

Takes a trade log DataFrame (the same shape produced by account_backtest.py
or rust_bridge.py -- must have at least a 'pnl_rupees' column, and an
'exit_date' column for the charts) and computes 5 standard metrics, plus
draws an equity curve and a drawdown chart.

WHAT EACH METRIC MEANS (plain English)
------------------------------------------
  TOTAL RETURN %
      How much your account balance grew, as a percentage of what you
      started with. formula: (final_balance - starting_balance) / starting_balance * 100
      e.g. going from 5,00,000 to 5,50,000 is a 10% total return.

  SHARPE RATIO
      "How smooth was the ride to get this profit?" It's the average
      profit per trade divided by how much that profit bounces around
      (its standard deviation). Two strategies can make the same total
      money, but the one with less erratic swings has a higher Sharpe --
      and is usually the one you'd trust more.
      formula: mean(trade P&L) / std(trade P&L)
      NOTE: this is a simple PER-TRADE Sharpe, not annualized to "per
      year" -- a common, honest shortcut when you only have a handful of
      trades (annualizing needs many more data points to mean anything).

  MAX DRAWDOWN
      The single worst decline from a peak balance to a later low point,
      as a %. It answers "what's the most pain I'd have sat through?"
      even if the strategy was profitable overall by the end.
      e.g. -12% means at some point your balance fell 12% below its
      highest point so far.

  WIN RATE
      Simply: % of trades that made money (pnl_rupees > 0).

  PROFIT FACTOR
      Total rupees won from winning trades, divided by total rupees lost
      from losing trades (as a positive number).
      formula: sum(winning P&L) / abs(sum(losing P&L))
      Above 1.0 = profitable overall. e.g. 2.0 means you won 2 rupees for
      every 1 rupee you lost.

WHAT THE EQUITY CURVE AND DRAWDOWN CHART SHOW
-------------------------------------------------
  EQUITY CURVE: your account balance over time, trade by trade. A
  strategy that's "working" should trend up-and-to-the-right, ideally
  without huge dips.

  DRAWDOWN CHART: at every point in time, how far below the highest
  balance-so-far you currently are (as a %). This is always <= 0. It
  makes the "pain" of a strategy much more visible than the equity curve
  alone -- a strategy can look fine on the equity curve and still have
  spent months underwater.
"""

from __future__ import annotations

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd


def compute_performance_metrics(trade_log: pd.DataFrame, starting_balance: float) -> dict:
    """Compute total return %, Sharpe ratio, max drawdown %, win rate %,
    and profit factor from a trade log. Requires a 'pnl_rupees' column."""
    if trade_log.empty:
        return {
            "num_trades": 0, "total_return_pct": 0.0, "sharpe": np.nan,
            "max_drawdown_pct": 0.0, "win_rate_pct": np.nan, "profit_factor": np.nan,
            "final_balance": starting_balance,
        }

    pnl = trade_log["pnl_rupees"]

    # --- Total return % ---
    final_balance = starting_balance + pnl.sum()
    total_return_pct = (final_balance - starting_balance) / starting_balance * 100

    # --- Sharpe ratio (per-trade, not annualized -- see module docstring) ---
    pnl_std = pnl.std(ddof=1)
    sharpe = pnl.mean() / pnl_std if pnl_std > 0 else np.nan

    # --- Max drawdown % (needs the equity curve -- see build_equity_curve) ---
    equity = build_equity_curve(trade_log, starting_balance)
    max_drawdown_pct = compute_drawdown_series(equity).min()

    # --- Win rate % ---
    win_rate_pct = (pnl > 0).mean() * 100

    # --- Profit factor ---
    gross_profit = pnl[pnl > 0].sum()
    gross_loss = -pnl[pnl < 0].sum()  # flip sign to make it positive
    if gross_loss > 0:
        profit_factor = gross_profit / gross_loss
    else:
        profit_factor = np.inf if gross_profit > 0 else np.nan

    return {
        "num_trades": len(trade_log),
        "total_return_pct": total_return_pct,
        "sharpe": sharpe,
        "max_drawdown_pct": max_drawdown_pct,
        "win_rate_pct": win_rate_pct,
        "profit_factor": profit_factor,
        "final_balance": final_balance,
    }


def build_equity_curve(trade_log: pd.DataFrame, starting_balance: float) -> pd.Series:
    """Account balance over time: starts at `starting_balance`, then adds
    each trade's P&L in the order trades closed (indexed by exit_date)."""
    if trade_log.empty:
        return pd.Series([starting_balance], name="balance")

    ordered = trade_log.sort_values("exit_date")
    balance = starting_balance + ordered["pnl_rupees"].cumsum()
    balance.index = pd.to_datetime(ordered["exit_date"])
    balance.name = "balance"
    return balance


def compute_drawdown_series(equity: pd.Series) -> pd.Series:
    """% below the running peak balance, at every point along the equity curve.
    Always <= 0 (0 means "at a new all-time high right now")."""
    running_peak = equity.cummax()
    drawdown_pct = (equity - running_peak) / running_peak * 100
    drawdown_pct.name = "drawdown_pct"
    return drawdown_pct


def plot_equity_curve(equity: pd.Series, save_path: str = "equity_curve.png") -> None:
    """Draw the account balance over time and save it as a PNG."""
    fig, ax = plt.subplots(figsize=(10, 5))
    ax.plot(equity.index, equity.values, color="#2a6f97", linewidth=2, marker="o")
    ax.set_title("Equity Curve (Account Balance Over Time)")
    ax.set_xlabel("Date")
    ax.set_ylabel("Account Balance (Rs)")
    ax.yaxis.set_major_formatter(lambda value, _: f"{value:,.0f}")
    ax.grid(True, alpha=0.3)
    fig.autofmt_xdate()
    fig.tight_layout()
    fig.savefig(save_path, dpi=150)
    plt.close(fig)
    print(f"Saved equity curve chart to {save_path}")


def plot_drawdown(equity: pd.Series, save_path: str = "drawdown_chart.png") -> None:
    """Draw the drawdown-from-peak % over time and save it as a PNG."""
    drawdown = compute_drawdown_series(equity)

    fig, ax = plt.subplots(figsize=(10, 4))
    ax.fill_between(drawdown.index, drawdown.values, 0, color="#c1121f", alpha=0.4)
    ax.plot(drawdown.index, drawdown.values, color="#c1121f", linewidth=1.5)
    ax.set_title("Drawdown (% Below Peak Balance)")
    ax.set_xlabel("Date")
    ax.set_ylabel("Drawdown (%)")
    ax.grid(True, alpha=0.3)
    fig.autofmt_xdate()
    fig.tight_layout()
    fig.savefig(save_path, dpi=150)
    plt.close(fig)
    print(f"Saved drawdown chart to {save_path}")


def generate_performance_report(trade_log: pd.DataFrame, starting_balance: float,
                                 equity_chart_path: str = "equity_curve.png",
                                 drawdown_chart_path: str = "drawdown_chart.png") -> dict:
    """Convenience: compute metrics AND save both charts in one call."""
    metrics = compute_performance_metrics(trade_log, starting_balance)
    equity = build_equity_curve(trade_log, starting_balance)
    plot_equity_curve(equity, equity_chart_path)
    plot_drawdown(equity, drawdown_chart_path)
    return metrics


if __name__ == "__main__":
    trade_log = pd.read_csv("test_trade_log.csv", parse_dates=["entry_date", "exit_date", "expiry"])
    metrics = generate_performance_report(trade_log, starting_balance=500_000.0)

    print("\nPerformance summary (test_trade_log.csv):")
    print(f"  Total return:  {metrics['total_return_pct']:.2f}%")
    print(f"  Sharpe ratio:  {metrics['sharpe']:.2f}")
    print(f"  Max drawdown:  {metrics['max_drawdown_pct']:.2f}%")
    print(f"  Win rate:      {metrics['win_rate_pct']:.1f}%")
    print(f"  Profit factor: {metrics['profit_factor']:.2f}")
    print(f"  Final balance: Rs {metrics['final_balance']:,.0f}")
