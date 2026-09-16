"""
Calls the compiled Rust extension (nifty_backtest_rs) instead of the pure
Python loop in account_backtest.py, and converts the results back into a
normal pandas DataFrame.

This file still does all the pandas-heavy prep work in Python (reading the
CSV, computing IV rank via iv_rank.py) -- only the actual day-by-day
entry/exit loop runs in Rust. That loop is the part that runs thousands of
times and benefits from being compiled, not the one-off setup work.

You must build the Rust extension first -- see README_RUST.md for the
step-by-step PyO3/maturin instructions.
"""

from __future__ import annotations

from datetime import date

import pandas as pd

from iv_rank import AtmIvConfig, build_iv_metrics
from option_lookup import DEFAULT_MIN_VOLUME
from strategy_config import StrategyConfig


def _to_ordinal(ts) -> int:
    """Convert a pandas Timestamp (or datetime.date) to a plain integer
    (days since a fixed reference point) -- see the note at the top of
    nifty_backtest_rs/src/lib.rs for why we do this."""
    return pd.Timestamp(ts).toordinal()


def run_account_backtest_rust(df: pd.DataFrame, config: StrategyConfig = None,
                               starting_balance: float = 500_000.0,
                               lot_size: int = 75,
                               min_volume: int = DEFAULT_MIN_VOLUME) -> tuple[pd.DataFrame, float]:
    # Importing here (not at the top of the file) gives a clearer error
    # message if the Rust extension hasn't been built yet.
    try:
        from nifty_backtest_rs import run_account_backtest_rs
    except ImportError as exc:
        raise ImportError(
            "Couldn't import the Rust extension 'nifty_backtest_rs'. "
            "Build it first: cd nifty_backtest_rs && maturin develop --release "
            "(see README_RUST.md)."
        ) from exc

    if config is None:
        config = StrategyConfig.default()
    entry_cfg, exit_cfg = config.entry, config.exit

    # --- Every trading day present in the data ---
    trading_days = [_to_ordinal(d) for d in sorted(df["date"].unique())]

    # --- Nifty's closing value each day (needed for strike selection + expiry settlement) ---
    spot_series = df.drop_duplicates("date").set_index("date")["underlying_close"]
    spot_dates = [_to_ordinal(d) for d in spot_series.index]
    spot_values = [float(v) for v in spot_series.values]

    # --- IV Rank / Percentile signal, computed exactly as before (iv_rank.py is unchanged) ---
    atm_cfg = AtmIvConfig(target_dte=entry_cfg.target_dte,
                           min_dte=entry_cfg.min_dte, max_dte=entry_cfg.max_dte)
    metrics = build_iv_metrics(df, atm_cfg, lookback=entry_cfg.iv_lookback_days)
    signal = metrics["iv_percentile" if entry_cfg.use_percentile else "iv_rank"].dropna()
    signal_dates = [_to_ordinal(d) for d in signal.index]
    signal_values = [float(v) for v in signal.values]

    # --- Every option row, as flat parallel lists (strike -> centi-rupees integer) ---
    opt_dates = [_to_ordinal(d) for d in df["date"]]
    opt_expiries = [_to_ordinal(d) for d in df["expiry"]]
    opt_strikes_centi = [int(round(s * 100)) for s in df["strike"]]
    opt_types = [0 if t == "CE" else 1 for t in df["option_type"]]  # 0=CE, 1=PE
    opt_closes = [float(c) for c in df["close"]]
    opt_volumes = [int(v) for v in df["volume"]]

    trades, final_balance = run_account_backtest_rs(
        trading_days,
        opt_dates, opt_expiries, opt_strikes_centi, opt_types, opt_closes,
        opt_volumes, int(min_volume),
        spot_dates, spot_values,
        signal_dates, signal_values,
        entry_cfg.iv_threshold,
        entry_cfg.short_call_otm_pct, entry_cfg.short_put_otm_pct, entry_cfg.wing_width_points,
        entry_cfg.target_dte, entry_cfg.min_dte, entry_cfg.max_dte,
        exit_cfg.profit_target_pct, exit_cfg.stop_loss_multiple, exit_cfg.exit_days_before_expiry,
        starting_balance, float(lot_size),
    )

    trade_log = pd.DataFrame(trades)
    if not trade_log.empty:
        for col in ("entry_date", "exit_date", "expiry"):
            trade_log[col] = trade_log[col].apply(lambda o: date.fromordinal(int(o)))

    return trade_log, final_balance


if __name__ == "__main__":
    df = pd.read_csv("tuning_data.csv", parse_dates=["date", "expiry"])

    config = StrategyConfig.default()
    config.entry.iv_lookback_days = 20
    config.entry.iv_threshold = 50.0

    trade_log, final_balance = run_account_backtest_rust(df, config)

    pd.set_option("display.width", 160)
    print(trade_log)
    print(f"\nFinal balance: Rs {final_balance:,.0f}")
