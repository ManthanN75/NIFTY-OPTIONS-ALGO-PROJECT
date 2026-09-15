"""
ACCOUNT-LEVEL BACKTEST: same strategy, but tracks a rupee account balance.

This reuses the entry/exit building blocks from iron_condor_backtest.py
(strike selection, mark-to-market, expiry settlement) so the trading logic
itself isn't duplicated -- this file only adds:
  1. Converting P&L from Nifty "points" to actual rupees (points * lot size).
  2. An account balance that starts at a fixed amount and updates each
     time a trade is CLOSED (we only realize P&L at exit, not day-by-day).
  3. A full trade log (as a list of dicts, easily turned into a DataFrame).

WHY POINTS -> RUPEES NEEDS A "LOT SIZE"
------------------------------------------
Nifty options aren't traded 1 point = 1 rupee. They trade in fixed-size
"lots" (NSE sets this, and has changed it over time). If the lot size is
75, then a position that made 100 points of profit made 100 * 75 = 7,500
rupees. This is a simple, deliberately unoptimized loop -- easy to read
and to check for correctness, not written for speed.
"""

from __future__ import annotations

import pandas as pd

from iron_condor_backtest import (
    IronCondorPosition,
    _cost_to_close_intrinsic,
    _cost_to_close_market,
    try_enter_iron_condor,
)
from iv_rank import AtmIvConfig, build_iv_metrics
from option_lookup import OptionPriceLookup
from strategy_config import StrategyConfig

STARTING_BALANCE = 500_000.0  # 5,00,000 rupees
LOT_SIZE = 75                  # Nifty lot size in contracts per lot (change if NSE updates it)


def run_account_backtest(df: pd.DataFrame, config: StrategyConfig = None,
                          starting_balance: float = STARTING_BALANCE,
                          lot_size: int = LOT_SIZE) -> tuple[pd.DataFrame, float]:
    """Loop through the data day by day, simulate the strategy, and track
    an account balance in rupees.

    Returns:
        trade_log: a DataFrame, one row per completed trade
        final_balance: the account balance in rupees after the last trade
    """
    if config is None:
        config = StrategyConfig.default()
    entry_cfg, exit_cfg = config.entry, config.exit

    lookup = OptionPriceLookup(df)
    spot_by_date = df.drop_duplicates("date").set_index("date")["underlying_close"]

    atm_cfg = AtmIvConfig(target_dte=entry_cfg.target_dte,
                           min_dte=entry_cfg.min_dte, max_dte=entry_cfg.max_dte)
    metrics = build_iv_metrics(df, atm_cfg, lookback=entry_cfg.iv_lookback_days)
    signal = metrics["iv_percentile" if entry_cfg.use_percentile else "iv_rank"]

    dates = sorted(df["date"].unique())

    balance = starting_balance
    open_position: IronCondorPosition | None = None
    prev_signal_value: float | None = None
    trade_log: list[dict] = []

    for date in dates:
        spot = spot_by_date.get(date)

        # --- Step 1: if a position is open, check whether today closes it ---
        if open_position is not None:
            dte_remaining = (open_position.expiry - date).days
            forced_expiry_exit = dte_remaining <= exit_cfg.exit_days_before_expiry

            exit_cost = None
            reason = None

            if forced_expiry_exit:
                exit_cost = _cost_to_close_intrinsic(spot, open_position)
                reason = "expiry"
            else:
                exit_cost = _cost_to_close_market(lookup, date, open_position)
                if exit_cost is not None:
                    pnl_points_now = open_position.entry_credit - exit_cost
                    if pnl_points_now >= exit_cfg.profit_target_pct * open_position.entry_credit:
                        reason = "profit_target"
                    elif pnl_points_now <= -exit_cfg.stop_loss_multiple * open_position.entry_credit:
                        reason = "stop_loss"

            if exit_cost is not None and reason is not None:
                pnl_points = open_position.entry_credit - exit_cost
                pnl_rupees = pnl_points * lot_size
                premium_collected_rupees = open_position.entry_credit * lot_size

                balance += pnl_rupees  # realize the P&L into the account balance

                trade_log.append({
                    "entry_date": open_position.entry_date,
                    "exit_date": date,
                    "expiry": open_position.expiry,
                    "short_call_strike": open_position.short_call_strike,
                    "short_put_strike": open_position.short_put_strike,
                    "long_call_strike": open_position.long_call_strike,
                    "long_put_strike": open_position.long_put_strike,
                    "premium_collected_points": open_position.entry_credit,
                    "premium_collected_rupees": premium_collected_rupees,
                    "exit_cost_points": exit_cost,
                    "pnl_points": pnl_points,
                    "pnl_rupees": pnl_rupees,
                    "exit_reason": reason,
                    "balance_after": balance,
                })
                open_position = None
            # else: no valid price today and not a forced exit -> just wait for the next day

        # --- Step 2: look for a fresh entry signal (only when flat) ---
        current_signal = signal.get(date, float("nan"))
        if open_position is None and current_signal == current_signal:  # not NaN
            crossed_above = (
                prev_signal_value is not None
                and prev_signal_value < entry_cfg.iv_threshold <= current_signal
            )
            if crossed_above:
                candidate = try_enter_iron_condor(lookup, date, spot, entry_cfg)
                if candidate is not None:
                    open_position = candidate

        if current_signal == current_signal:  # not NaN
            prev_signal_value = current_signal

    trade_log_df = pd.DataFrame(trade_log)
    return trade_log_df, balance


if __name__ == "__main__":
    df = pd.read_csv("tuning_data.csv", parse_dates=["date", "expiry"])

    # Use a shorter IV lookback than the default so trades actually fire
    # within this ~4-month tuning window (see prior discussion).
    config = StrategyConfig.default()
    config.entry.iv_lookback_days = 20
    config.entry.iv_threshold = 50.0

    trade_log, final_balance = run_account_backtest(df, config)

    pd.set_option("display.width", 160)
    print(trade_log)
    print(f"\nStarting balance: Rs {STARTING_BALANCE:,.0f}")
    print(f"Final balance:    Rs {final_balance:,.0f}")
    print(f"Net P&L:          Rs {final_balance - STARTING_BALANCE:,.0f}")
    if not trade_log.empty:
        print(f"Trades: {len(trade_log)}  |  Win rate: {(trade_log['pnl_rupees'] > 0).mean() * 100:.1f}%")
