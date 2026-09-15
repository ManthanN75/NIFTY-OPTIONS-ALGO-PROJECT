"""
THE BACKTEST ENGINE: simulates selling iron condors over historical data.

This ties together:
  - iv_rank.py           -> tells us when options are "expensive" (high IV rank)
  - strategy_config.py    -> all the adjustable entry/exit thresholds
  - option_lookup.py      -> fast historical option price lookups

HOW A "CREDIT" POSITION'S PROFIT/LOSS WORKS
----------------------------------------------
When we SELL an iron condor, we receive money upfront (the "credit").
To close the position before expiry, we do the opposite trades (buy back
what we sold, sell what we bought), which has some cost (the "debit to
close"). Our profit is simply:

    profit = credit_received_at_entry - cost_to_close_now

If the cost to close has dropped (options got cheaper, e.g. because
nothing much happened and time passed), we make money. If it's risen
(e.g. Nifty moved sharply towards one of our strikes), we lose money.

AT EXPIRY
-----------
NSE cash-settles index options at expiry based on "intrinsic value"
(how far in-the-money the option ended up), not on the last traded price
-- and for far-OTM/illiquid strikes the last traded price in our data can
be stale or missing anyway. So for the forced expiry exit specifically, we
calculate the closing cost using intrinsic value instead of looking up a
traded price. This is both more realistic and more robust.

    Call intrinsic value = max(spot_price - strike, 0)
    Put intrinsic value  = max(strike - spot_price, 0)
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from iv_rank import AtmIvConfig, build_iv_metrics
from option_lookup import OptionPriceLookup, nearest_strike
from strategy_config import EntryConfig, ExitConfig, StrategyConfig


@dataclass
class IronCondorPosition:
    """The 4 legs and entry details of one open iron condor."""
    entry_date: pd.Timestamp
    expiry: pd.Timestamp
    short_call_strike: float
    short_put_strike: float
    long_call_strike: float
    long_put_strike: float
    entry_credit: float  # money received when the position was opened


@dataclass
class ClosedTrade:
    """A finished (entered AND exited) iron condor, for the trade log."""
    entry_date: pd.Timestamp
    exit_date: pd.Timestamp
    expiry: pd.Timestamp
    short_call_strike: float
    short_put_strike: float
    long_call_strike: float
    long_put_strike: float
    entry_credit: float
    exit_cost: float
    pnl: float
    exit_reason: str  # "profit_target" | "stop_loss" | "expiry"


def _intrinsic_value(spot: float, strike: float, option_type: str) -> float:
    if option_type == "CE":
        return max(spot - strike, 0.0)
    else:  # "PE"
        return max(strike - spot, 0.0)


def _pick_entry_expiry(lookup: OptionPriceLookup, date: pd.Timestamp,
                        cfg: EntryConfig) -> pd.Timestamp | None:
    """Choose which expiry to trade: closest to `target_dte`, within [min_dte, max_dte]."""
    expiries = lookup.expiries_available(date)
    candidates = []
    for exp in expiries:
        dte = (exp - date).days
        if cfg.min_dte <= dte <= cfg.max_dte:
            candidates.append((exp, dte))
    if not candidates:
        return None
    return min(candidates, key=lambda pair: abs(pair[1] - cfg.target_dte))[0]


def try_enter_iron_condor(lookup: OptionPriceLookup, date: pd.Timestamp, spot: float,
                           cfg: EntryConfig) -> IronCondorPosition | None:
    """Attempt to build a valid, prices-available iron condor for this day.

    Returns None (and the caller just tries again next day) if:
      - there's no suitable expiry available,
      - the target strikes aren't listed / didn't trade that day,
      - or the resulting position would be a net DEBIT (shouldn't happen
        for a properly-placed condor, but we check anyway as a sanity guard).
    """
    expiry = _pick_entry_expiry(lookup, date, cfg)
    if expiry is None:
        return None

    strikes = lookup.strikes_available(date, expiry)
    if not strikes:
        return None

    # Step 1: place the SHORT strikes a target % away from spot, snapped to a real strike.
    raw_short_call = spot * (1 + cfg.short_call_otm_pct)
    raw_short_put = spot * (1 - cfg.short_put_otm_pct)
    short_call_strike = nearest_strike(raw_short_call, strikes)
    short_put_strike = nearest_strike(raw_short_put, strikes)

    # Step 2: place the LONG (hedge) strikes further out by `wing_width_points`.
    long_call_strike = nearest_strike(short_call_strike + cfg.wing_width_points, strikes)
    long_put_strike = nearest_strike(short_put_strike - cfg.wing_width_points, strikes)

    # Sanity check: hedges must actually be further out than the shorts,
    # otherwise this isn't a real "condor" (it'd have no protection, or
    # negative width, if strikes were too sparse near this spot price).
    if not (long_call_strike > short_call_strike and long_put_strike < short_put_strike):
        return None

    short_call_price = lookup.price(date, expiry, short_call_strike, "CE")
    short_put_price = lookup.price(date, expiry, short_put_strike, "PE")
    long_call_price = lookup.price(date, expiry, long_call_strike, "CE")
    long_put_price = lookup.price(date, expiry, long_put_strike, "PE")

    if None in (short_call_price, short_put_price, long_call_price, long_put_price):
        return None  # one of the 4 legs simply didn't trade today -- skip this attempt

    entry_credit = (short_call_price + short_put_price) - (long_call_price + long_put_price)
    if entry_credit <= 0:
        return None  # would be a net debit -- not a sensible condor, skip

    return IronCondorPosition(
        entry_date=date, expiry=expiry,
        short_call_strike=short_call_strike, short_put_strike=short_put_strike,
        long_call_strike=long_call_strike, long_put_strike=long_put_strike,
        entry_credit=entry_credit,
    )


def _cost_to_close_market(lookup: OptionPriceLookup, date: pd.Timestamp,
                           pos: IronCondorPosition) -> float | None:
    """What it would cost to close the position TODAY, using traded prices.
    Returns None if any leg's price isn't available today (illiquid day)."""
    sc = lookup.price(date, pos.expiry, pos.short_call_strike, "CE")
    sp = lookup.price(date, pos.expiry, pos.short_put_strike, "PE")
    lc = lookup.price(date, pos.expiry, pos.long_call_strike, "CE")
    lp = lookup.price(date, pos.expiry, pos.long_put_strike, "PE")
    if None in (sc, sp, lc, lp):
        return None
    return (sc + sp) - (lc + lp)


def _cost_to_close_intrinsic(spot: float, pos: IronCondorPosition) -> float:
    """What it costs to close at expiry, using intrinsic value (see module
    docstring for why we do this instead of using traded prices at expiry)."""
    sc = _intrinsic_value(spot, pos.short_call_strike, "CE")
    sp = _intrinsic_value(spot, pos.short_put_strike, "PE")
    lc = _intrinsic_value(spot, pos.long_call_strike, "CE")
    lp = _intrinsic_value(spot, pos.long_put_strike, "PE")
    return (sc + sp) - (lc + lp)


def run_backtest(df: pd.DataFrame, config: StrategyConfig = None) -> list[ClosedTrade]:
    """Run the full entry/exit simulation over the given options DataFrame
    (e.g. tuning_data.csv) and return the list of completed trades."""
    if config is None:
        config = StrategyConfig.default()
    entry_cfg, exit_cfg = config.entry, config.exit

    lookup = OptionPriceLookup(df)
    spot_by_date = df.drop_duplicates("date").set_index("date")["underlying_close"]

    # Use the same target/min/max DTE for the IV-rank reference expiry as
    # for actual trade entries, so "is IV high right now" reflects options
    # of a similar tenor to what we're about to trade.
    atm_cfg = AtmIvConfig(target_dte=entry_cfg.target_dte,
                           min_dte=entry_cfg.min_dte, max_dte=entry_cfg.max_dte)
    metrics = build_iv_metrics(df, atm_cfg, lookback=entry_cfg.iv_lookback_days)
    signal = metrics["iv_percentile" if entry_cfg.use_percentile else "iv_rank"]

    dates = sorted(df["date"].unique())
    trades: list[ClosedTrade] = []
    open_position: IronCondorPosition | None = None
    prev_signal_value: float | None = None

    for date in dates:
        spot = spot_by_date.get(date)

        # --- 1) Manage an already-open position: mark to market, check exits ---
        if open_position is not None:
            dte_remaining = (open_position.expiry - date).days
            forced_expiry_exit = dte_remaining <= exit_cfg.exit_days_before_expiry

            if forced_expiry_exit:
                exit_cost = _cost_to_close_intrinsic(spot, open_position)
                reason = "expiry"
            else:
                exit_cost = _cost_to_close_market(lookup, date, open_position)
                reason = None
                if exit_cost is not None:
                    pnl_now = open_position.entry_credit - exit_cost
                    if pnl_now >= exit_cfg.profit_target_pct * open_position.entry_credit:
                        reason = "profit_target"
                    elif pnl_now <= -exit_cfg.stop_loss_multiple * open_position.entry_credit:
                        reason = "stop_loss"

            if exit_cost is not None and reason is not None:
                pnl = open_position.entry_credit - exit_cost
                trades.append(ClosedTrade(
                    entry_date=open_position.entry_date, exit_date=date,
                    expiry=open_position.expiry,
                    short_call_strike=open_position.short_call_strike,
                    short_put_strike=open_position.short_put_strike,
                    long_call_strike=open_position.long_call_strike,
                    long_put_strike=open_position.long_put_strike,
                    entry_credit=open_position.entry_credit,
                    exit_cost=exit_cost, pnl=pnl, exit_reason=reason,
                ))
                open_position = None
            # if exit_cost is None and not a forced exit, we just wait -- no
            # prices today for this contract, try again on the next trading day.

        # --- 2) Look for a new entry signal (only if we have no open position) ---
        current_signal = signal.get(date, np.nan)
        if open_position is None and not np.isnan(current_signal):
            crossed_above = (
                prev_signal_value is not None
                and prev_signal_value < entry_cfg.iv_threshold <= current_signal
            )
            if crossed_above:
                candidate = try_enter_iron_condor(lookup, date, spot, entry_cfg)
                if candidate is not None:
                    open_position = candidate

        if not np.isnan(current_signal):
            prev_signal_value = current_signal

    return trades


def trades_to_dataframe(trades: list[ClosedTrade]) -> pd.DataFrame:
    """Convenience: turn the trade list into a DataFrame for easy viewing/export."""
    return pd.DataFrame([vars(t) for t in trades])


if __name__ == "__main__":
    df = pd.read_csv("tuning_data.csv", parse_dates=["date", "expiry"])
    trades = run_backtest(df, StrategyConfig.default())
    trades_df = trades_to_dataframe(trades)

    print(trades_df)
    if not trades_df.empty:
        win_rate = (trades_df["pnl"] > 0).mean() * 100
        print(f"\nTrades: {len(trades_df)}")
        print(f"Win rate: {win_rate:.1f}%")
        print(f"Total P&L: {trades_df['pnl'].sum():.1f} points")
        print(f"Average P&L per trade: {trades_df['pnl'].mean():.1f} points")
        print(trades_df["exit_reason"].value_counts())
    else:
        print("No trades were triggered with this configuration/date range.")
