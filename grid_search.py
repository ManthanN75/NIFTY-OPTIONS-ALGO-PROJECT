"""
GRID SEARCH: try every combination of IV-rank threshold and profit target,
run the (Rust-backed) backtest for each, and compare them side by side.

WHAT EACH METRIC MEANS (for beginners)
-----------------------------------------
  - win_rate:        % of trades that made money.
  - sharpe:          average profit per trade, divided by how much that
                      profit swings around (its standard deviation). Higher
                      is better -- it rewards consistent profits and
                      punishes wild swings, not just raw total profit.
                      NOTE: this is a simple PER-TRADE Sharpe (not
                      annualized to "per year"), which is a common
                      shortcut for options-selling strategies that only
                      trade a handful of times -- there often aren't
                      enough trades to annualize meaningfully.
  - max_drawdown_pct: the worst peak-to-trough decline in account balance
                      you'd have lived through, as a %. e.g. -8% means at
                      some point you were down 8% from your best-ever
                      balance so far. Smaller (closer to 0) is better.
  - profit_factor:   total rupees won / total rupees lost. Above 1 means
                      profitable overall; e.g. 2.0 means you made 2 rupees
                      for every 1 rupee lost.

Because this only runs on tuning_data.csv, remember the point of tuning:
find settings that look GOOD here, then confirm them ONCE on test_data.csv
later -- don't keep re-tuning against test_data.csv itself.
"""

from __future__ import annotations

from dataclasses import replace
from itertools import product

import numpy as np
import pandas as pd

from rust_bridge import run_account_backtest_rust
from strategy_config import StrategyConfig


def compute_metrics(trade_log: pd.DataFrame, starting_balance: float) -> dict:
    """Turn a trade log into the 4 comparison metrics (+ some extras)."""
    if trade_log.empty:
        return {
            "num_trades": 0, "win_rate": np.nan, "sharpe": np.nan,
            "max_drawdown_pct": np.nan, "profit_factor": np.nan,
            "total_pnl": 0.0, "final_balance": starting_balance,
        }

    pnl = trade_log["pnl_rupees"]
    wins = pnl[pnl > 0]
    losses = pnl[pnl < 0]

    win_rate = (pnl > 0).mean() * 100

    pnl_std = pnl.std(ddof=1)
    sharpe = pnl.mean() / pnl_std if pnl_std > 0 else np.nan

    gross_profit = wins.sum()
    gross_loss = -losses.sum()  # make positive
    if gross_loss > 0:
        profit_factor = gross_profit / gross_loss
    else:
        profit_factor = np.inf if gross_profit > 0 else np.nan

    # Build the running account balance (equity curve) trade by trade, in
    # the order trades actually closed, to measure the worst drawdown.
    equity = pd.concat([pd.Series([starting_balance]), starting_balance + pnl.cumsum()],
                        ignore_index=True)
    running_peak = equity.cummax()
    drawdown_pct = (equity - running_peak) / running_peak * 100
    max_drawdown_pct = drawdown_pct.min()  # most negative value

    return {
        "num_trades": len(trade_log),
        "win_rate": win_rate,
        "sharpe": sharpe,
        "max_drawdown_pct": max_drawdown_pct,
        "profit_factor": profit_factor,
        "total_pnl": pnl.sum(),
        "final_balance": starting_balance + pnl.sum(),
    }


def run_grid_search(df: pd.DataFrame, iv_thresholds: list[float], profit_targets: list[float],
                     base_config: StrategyConfig = None,
                     starting_balance: float = 500_000.0, lot_size: int = 75) -> pd.DataFrame:
    """Run the Rust-backed backtest once per (iv_threshold, profit_target)
    combination and return one row of metrics per combination."""
    base = base_config or StrategyConfig.default()

    rows = []
    for iv_threshold, profit_target in product(iv_thresholds, profit_targets):
        entry_cfg = replace(base.entry, iv_threshold=iv_threshold)
        exit_cfg = replace(base.exit, profit_target_pct=profit_target)
        config = StrategyConfig(entry=entry_cfg, exit=exit_cfg)

        trade_log, _ = run_account_backtest_rust(df, config, starting_balance, lot_size)
        metrics = compute_metrics(trade_log, starting_balance)

        rows.append({
            "iv_threshold": iv_threshold,
            "profit_target_pct": profit_target * 100,  # show as e.g. 50.0, not 0.5
            **metrics,
        })

    return pd.DataFrame(rows)


if __name__ == "__main__":
    df = pd.read_csv("tuning_data.csv", parse_dates=["date", "expiry"])

    # Shorter IV lookback than the default 60, because tuning_data.csv is
    # only ~4 months (~80 trading days) -- see earlier discussion. Adjust
    # freely; it applies to every grid cell below.
    base_config = StrategyConfig.default()
    base_config.entry.iv_lookback_days = 20

    iv_thresholds = [60, 65, 70, 75, 80]
    profit_targets = [0.30, 0.40, 0.50]

    results = run_grid_search(df, iv_thresholds, profit_targets, base_config)

    # Sort best-Sharpe-first so the most attractive settings are at the top.
    results = results.sort_values("sharpe", ascending=False).reset_index(drop=True)

    pd.set_option("display.width", 160)
    pd.set_option("display.float_format", lambda x: f"{x:,.2f}")
    print(results.to_string(index=False))

    results.to_csv("grid_search_results.csv", index=False)
    print("\nSaved full results to grid_search_results.csv")
