"""
FULL 24-MONTH TEST, POST LIQUIDITY-BUG FIX.

WHY THIS SCRIPT EXISTS (AND WHY IT'S NOT SPLIT INTO TUNING/TEST)
--------------------------------------------------------------------
Auditing the earlier 10-month (4 tuning / 6 test) result by hand found a
real bug: the backtest was pricing some trade legs using stale,
zero-volume "close" prices from NSE's bhavcopy (a contract nobody traded
that day still lists a frozen last price) -- this inflated the win rate,
because profit-target exits were firing on price moves that were never
actually tradeable. That's fixed now (see option_lookup.py and
nifty_backtest_rs/src/lib.rs's liquidity filter).

This run does NOT re-tune parameters. It reuses the settings already
chosen from the earlier grid search (iv_threshold=80, profit_target=50%,
iv_lookback_days=20) and simply re-runs them -- now correctly, with the
liquidity fix -- across a much longer history (24 months instead of 10),
to get a bigger, more trustworthy trade sample. Re-tuning against this
data would defeat the point (see evaluate_on_test.py and every prior
discussion of the tuning/test discipline in this project) -- this is a
verification run of an already-fixed, already-chosen strategy, not a
fresh search.

WHAT IT PRODUCES
-------------------
  data_24m.csv           -- the full cleaned 24-month dataset (no split)
  results_24m.xlsx        -- Summary / Trade Log / Equity Curve, in Excel
  equity_curve_24m.png    -- equity curve chart
  drawdown_chart_24m.png  -- drawdown chart
"""

from __future__ import annotations

import pandas as pd

from build_full_dataset import build_and_save
from export_excel import export_results_to_excel
from performance_report import build_equity_curve, compute_performance_metrics, plot_drawdown, plot_equity_curve
from rust_bridge import run_account_backtest_rust
from strategy_config import EntryConfig, ExitConfig, StrategyConfig

STARTING_BALANCE = 500_000.0
LOT_SIZE = 75

# The settings already chosen from tuning (see evaluate_on_test.py) --
# reused as-is, not re-searched, to keep this an honest verification run.
IV_THRESHOLD = 80
PROFIT_TARGET_PCT = 0.50
IV_LOOKBACK_DAYS = 20


def build_config() -> StrategyConfig:
    entry = EntryConfig(iv_threshold=IV_THRESHOLD, iv_lookback_days=IV_LOOKBACK_DAYS)
    exit_ = ExitConfig(profit_target_pct=PROFIT_TARGET_PCT)
    return StrategyConfig(entry=entry, exit=exit_)


if __name__ == "__main__":
    print("=" * 70)
    print("STEP 1/3: Building the full 24-month cleaned dataset")
    print("=" * 70)
    df = build_and_save()

    print("\n" + "=" * 70)
    print("STEP 2/3: Running the (liquidity-fixed) backtest across all 24 months")
    print("=" * 70)
    config = build_config()
    trade_log, final_balance = run_account_backtest_rust(df, config, STARTING_BALANCE, LOT_SIZE)
    print(trade_log if not trade_log.empty else "(no trades triggered)")

    metrics = compute_performance_metrics(trade_log, STARTING_BALANCE)
    equity = build_equity_curve(trade_log, STARTING_BALANCE)

    print(f"\nTrades: {metrics['num_trades']}")
    print(f"Total return: {metrics['total_return_pct']:.2f}%")
    print(f"Win rate: {metrics['win_rate_pct']:.1f}%")
    print(f"Sharpe: {metrics['sharpe']:.2f}")
    print(f"Max drawdown: {metrics['max_drawdown_pct']:.2f}%")
    print(f"Profit factor: {metrics['profit_factor']:.2f}")

    print("\n" + "=" * 70)
    print("STEP 3/3: Exporting results (Excel + charts)")
    print("=" * 70)
    export_results_to_excel(trade_log, metrics, equity, STARTING_BALANCE, "results_24m.xlsx")
    plot_equity_curve(equity, "equity_curve_24m.png")
    plot_drawdown(equity, "drawdown_chart_24m.png")

    print("\nDone. See results_24m.xlsx, equity_curve_24m.png, drawdown_chart_24m.png")
