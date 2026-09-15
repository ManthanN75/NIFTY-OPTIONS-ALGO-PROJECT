"""
FINAL, ONE-TIME EVALUATION on test_data.csv (the 4 months tuning never saw).

WHY THIS SCRIPT IS DELIBERATELY RIGID
----------------------------------------
The whole point of keeping test_data.csv separate (see README.md) is to
get an honest read of performance on data the strategy was never adjusted
against. That only works if you run it EXACTLY ONCE with the settings you
already committed to from tuning -- if you peek at the test result, don't
like it, and tweak a parameter, you've quietly turned test_data.csv into
more tuning data, and the "honest read" is gone.

So: the winning settings below are hard-coded, not searched for. If you
want to try different settings, go back and explore on tuning_data.csv,
then update this file deliberately (and know you're spending your one
"clean" look at the test set).

WINNING SETTINGS (from grid_search.py on tuning_data.csv,
2025-11-18 to 2026-03-17, the current 4-month tuning window)
------------------------------------------------------------
iv_threshold = 80, profit_target_pct = 50% -- picked because it had the
LEAST BAD Sharpe ratio among the 15 combinations tried (-0.10). Worth
being blunt about: every single combination in this grid produced a
negative or barely-positive Sharpe on this tuning window -- there was no
genuinely good setting to pick, only a "least bad" one. That's a real
result, not a bug: it's telling you this particular 4-month window
(mostly calm/low-vol) didn't reward this strategy. Treat the test-period
numbers below with that in mind.
"""

from __future__ import annotations

from dataclasses import replace

import pandas as pd

from grid_search import compute_metrics
from rust_bridge import run_account_backtest_rust
from strategy_config import StrategyConfig

# --- The settings selected from tuning -- do not tweak these here. ---
BEST_IV_THRESHOLD = 80
BEST_PROFIT_TARGET_PCT = 0.50
IV_LOOKBACK_DAYS = 20  # same lookback used throughout the tuning grid search

STARTING_BALANCE = 500_000.0
LOT_SIZE = 75


def build_best_config() -> StrategyConfig:
    base = StrategyConfig.default()
    base.entry.iv_lookback_days = IV_LOOKBACK_DAYS
    entry_cfg = replace(base.entry, iv_threshold=BEST_IV_THRESHOLD)
    exit_cfg = replace(base.exit, profit_target_pct=BEST_PROFIT_TARGET_PCT)
    return StrategyConfig(entry=entry_cfg, exit=exit_cfg)


def print_metrics(label: str, metrics: dict) -> None:
    print(f"\n{label}")
    print(f"  Trades:            {metrics['num_trades']}")
    print(f"  Win rate:          {metrics['win_rate']:.1f}%")
    print(f"  Sharpe (per-trade):{metrics['sharpe']:.2f}")
    print(f"  Max drawdown:      {metrics['max_drawdown_pct']:.2f}%")
    print(f"  Profit factor:     {metrics['profit_factor']:.2f}")
    print(f"  Total P&L:         Rs {metrics['total_pnl']:,.0f}")
    print(f"  Final balance:     Rs {metrics['final_balance']:,.0f}")


if __name__ == "__main__":
    config = build_best_config()

    # --- Run on test_data.csv (the one-time, honest evaluation) ---
    test_df = pd.read_csv("test_data.csv", parse_dates=["date", "expiry"])
    test_trade_log, test_final_balance = run_account_backtest_rust(
        test_df, config, STARTING_BALANCE, LOT_SIZE
    )
    test_metrics = compute_metrics(test_trade_log, STARTING_BALANCE)

    pd.set_option("display.width", 160)
    print("=" * 70)
    print(f"TEST-PERIOD trade log (iv_threshold={BEST_IV_THRESHOLD}, "
          f"profit_target={BEST_PROFIT_TARGET_PCT*100:.0f}%)")
    print("=" * 70)
    print(test_trade_log if not test_trade_log.empty else "(no trades triggered)")
    test_trade_log.to_csv("test_trade_log.csv", index=False)

    print_metrics("TEST PERIOD (test_data.csv -- unseen data)", test_metrics)

    # --- For comparison, re-run the SAME settings on tuning_data.csv ---
    # (Not re-tuning -- just showing the already-known tuning-period result
    # side by side with the new test-period result.)
    tuning_df = pd.read_csv("tuning_data.csv", parse_dates=["date", "expiry"])
    tuning_trade_log, _ = run_account_backtest_rust(tuning_df, config, STARTING_BALANCE, LOT_SIZE)
    tuning_metrics = compute_metrics(tuning_trade_log, STARTING_BALANCE)

    print_metrics("TUNING PERIOD (tuning_data.csv -- same settings, for comparison)", tuning_metrics)

    print("\n" + "=" * 70)
    print("TUNING vs TEST comparison")
    print("=" * 70)
    comparison = pd.DataFrame([
        {"period": "tuning", **tuning_metrics},
        {"period": "test", **test_metrics},
    ])
    print(comparison.to_string(index=False))
    comparison.to_csv("tuning_vs_test_comparison.csv", index=False)

    print("\nSaved: test_trade_log.csv, tuning_vs_test_comparison.csv")
