"""
IV RANK / IV PERCENTILE
=========================
These are two ways of answering the question: "Is Nifty's implied
volatility (IV) high or low RIGHT NOW, compared to its own recent past?"

A raw IV number (like "14%") doesn't tell you much on its own -- 14% might
be high for a calm month and low for a wild one. IV Rank and IV Percentile
solve this by comparing today's IV to a trailing window of past days.

  IV RANK (0-100):
      (today's IV - lowest IV in window) / (highest IV in window - lowest IV in window) * 100
      "Where does today sit between the window's low and high?"
      e.g. IV Rank = 80 means today's IV is near the TOP of its recent range.

  IV PERCENTILE (0-100):
      % of days in the window where IV was LOWER than today.
      e.g. IV Percentile = 80 means today's IV is higher than 80% of the
      past days in the window.

Iron condor sellers like HIGH IV rank/percentile, because it means options
are relatively "expensive" right now (more premium to collect) and IV has
more room to fall back down (which helps a premium-selling position).

WHICH "IV" DO WE TRACK DAY TO DAY?
------------------------------------
Every single day has hundreds of options (different strikes, different
expiries), each with its own IV. To get ONE representative IV number per
day, we use the "ATM IV": the implied volatility of the option whose
strike is closest to Nifty's current price (ATM = "At The Money"), from an
expiry that's roughly a set number of days away (not too close to expiry,
where IV gets noisy/unreliable; not too far, where liquidity thins out).
We average the call (CE) and put (PE) IV at that strike, since both
should theoretically be very similar for the same strike/expiry.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd


@dataclass
class AtmIvConfig:
    """Controls which expiry counts as 'the' expiry for the daily ATM IV."""
    target_dte: int = 30   # ideally look at an expiry ~30 calendar days out
    min_dte: int = 7        # but never closer than this (avoids expiry-day noise)
    max_dte: int = 45       # and never further than this (avoids stale/illiquid data)


def _pick_reference_expiry(day_df: pd.DataFrame, as_of_date: pd.Timestamp,
                            cfg: AtmIvConfig) -> pd.Timestamp | None:
    """Out of the expiries available on this day, pick the one closest to
    `target_dte` days away, but only if it's within [min_dte, max_dte]."""
    expiries = day_df["expiry"].unique()
    dte = (pd.to_datetime(expiries) - as_of_date).days
    candidates = [(exp, d) for exp, d in zip(expiries, dte) if cfg.min_dte <= d <= cfg.max_dte]
    if not candidates:
        return None
    # pick whichever candidate's dte is closest to the target
    best = min(candidates, key=lambda pair: abs(pair[1] - cfg.target_dte))
    return pd.Timestamp(best[0])


def _atm_iv_for_day(day_df: pd.DataFrame, expiry: pd.Timestamp) -> float | None:
    """Average CE+PE implied volatility at the strike closest to spot."""
    exp_df = day_df[day_df["expiry"] == expiry]
    if exp_df.empty:
        return None

    spot = exp_df["underlying_close"].iloc[0]
    atm_strike = exp_df.loc[(exp_df["strike"] - spot).abs().idxmin(), "strike"]

    at_strike = exp_df[exp_df["strike"] == atm_strike]
    ivs = at_strike["implied_volatility"].dropna()
    if ivs.empty:
        return None
    return float(ivs.mean())


def build_atm_iv_series(df: pd.DataFrame, cfg: AtmIvConfig = AtmIvConfig()) -> pd.Series:
    """Build one ATM-IV value per trading day, as a Series indexed by date.

    This scans the full options DataFrame day by day, picks a reference
    expiry per the rules in AtmIvConfig, and records that day's ATM IV.
    Days where no suitable expiry/strike/IV is found are simply skipped
    (left out of the resulting Series) -- downstream code treats gaps as
    "unknown, don't trade".
    """
    values = {}
    for as_of_date, day_df in df.groupby("date"):
        expiry = _pick_reference_expiry(day_df, as_of_date, cfg)
        if expiry is None:
            continue
        iv = _atm_iv_for_day(day_df, expiry)
        if iv is not None:
            values[as_of_date] = iv

    series = pd.Series(values).sort_index()
    series.name = "atm_iv"
    return series


def rolling_iv_rank(iv_series: pd.Series, lookback: int = 60) -> pd.Series:
    """IV Rank per day: today's IV vs the [min, max] of the trailing window.

    `lookback` = how many past trading days count as "recent history".
    A shorter lookback (e.g. 20) reacts faster but is noisier; a longer
    one (e.g. 90+) is more stable but slower to reflect regime changes.
    The first `lookback` days won't have enough history and will be NaN.
    """
    rolling_min = iv_series.rolling(lookback).min()
    rolling_max = iv_series.rolling(lookback).max()
    span = (rolling_max - rolling_min).replace(0, np.nan)  # avoid divide-by-zero
    rank = (iv_series - rolling_min) / span * 100
    rank.name = "iv_rank"
    return rank


def rolling_iv_percentile(iv_series: pd.Series, lookback: int = 60) -> pd.Series:
    """IV Percentile per day: % of the trailing window's days with lower IV."""
    def pct_below(window: np.ndarray) -> float:
        today = window[-1]
        return float((window < today).sum()) / (len(window) - 1) * 100 if len(window) > 1 else np.nan

    pct = iv_series.rolling(lookback).apply(pct_below, raw=True)
    pct.name = "iv_percentile"
    return pct


def build_iv_metrics(df: pd.DataFrame, atm_cfg: AtmIvConfig = AtmIvConfig(),
                      lookback: int = 60) -> pd.DataFrame:
    """Convenience: build a small DataFrame with atm_iv, iv_rank, iv_percentile,
    one row per trading day."""
    atm_iv = build_atm_iv_series(df, atm_cfg)
    rank = rolling_iv_rank(atm_iv, lookback)
    pct = rolling_iv_percentile(atm_iv, lookback)
    return pd.concat([atm_iv, rank, pct], axis=1)


if __name__ == "__main__":
    df = pd.read_csv("tuning_data.csv", parse_dates=["date", "expiry"])
    metrics = build_iv_metrics(df)
    print(metrics.head(70))
    print(f"\n{metrics['iv_rank'].notna().sum()} days have a valid IV Rank "
          f"out of {len(metrics)} total days.")
