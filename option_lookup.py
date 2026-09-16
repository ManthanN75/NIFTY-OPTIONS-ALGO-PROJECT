"""
FAST LOOKUPS: "what did THIS option cost on THIS day, and could we
actually have traded it?"

During the backtest we constantly need to ask things like "what was the
23800 CE expiring 2026-03-31 worth on 2026-03-05?". Searching the whole
DataFrame with a filter every time would be slow (hundreds of thousands
of rows). So we build one lookup table, indexed by
(date, expiry, strike, option_type), once -- then every price lookup
afterwards is instant.

WHY THIS ALSO CHECKS TRADING VOLUME (IMPORTANT BUG FIX)
------------------------------------------------------------
NSE's bhavcopy lists a "close" price for every contract that EXISTS, even
ones nobody traded that day -- for an untraded contract, that price is
just whatever it last settled at, possibly days or weeks old, frozen in
place. It is not a real, tradeable price.

An earlier version of this backtest used that price anyway, which let the
strategy "sell" or "buy back" options at stale, made-up prices -- this
quietly inflated the win rate, because profit-target checks were firing
on price moves that were never actually tradeable (see the illiquid-leg
bug found by manually auditing the trade log: one leg's price was
IDENTICAL on entry and exit with zero trading volume in between, yet
still counted as a real 2-day profit).

The fix: `price()` now returns None (treated exactly like "no price
available at all") unless the contract actually traded enough that day.
That's controlled by `min_volume` -- require at least this many contracts
traded that day before trusting the price.
"""

from __future__ import annotations

import pandas as pd

# A contract needs at least this much trading volume on a given day for
# its "close" price to be treated as real and tradeable. 1 is a low bar
# (just "at least one real trade happened"), but it already rules out the
# frozen-stale-price case that caused the inflated win rate.
DEFAULT_MIN_VOLUME = 1


class OptionPriceLookup:
    """Wraps the options DataFrame for fast (date, expiry, strike, type) ->
    close price lookups, filtered to only contracts that actually traded."""

    def __init__(self, df: pd.DataFrame, min_volume: int = DEFAULT_MIN_VOLUME):
        self.min_volume = min_volume
        indexed = df.set_index(["date", "expiry", "strike", "option_type"]).sort_index()
        self._close = indexed["close"]
        self._volume = indexed["volume"] if "volume" in indexed.columns else None

    def price(self, date, expiry, strike, option_type) -> float | None:
        """Return the closing price of one option contract, or None if it
        didn't trade at all, doesn't exist for that combination, or didn't
        trade ENOUGH that day to trust the price (see module docstring)."""
        key = (date, expiry, strike, option_type)
        try:
            value = self._close.loc[key]
        except KeyError:
            return None
        # If duplicate rows ever slipped through, .loc could return a Series.
        if isinstance(value, pd.Series):
            value = value.iloc[0]

        if self._volume is not None:
            volume = self._volume.loc[key]
            if isinstance(volume, pd.Series):
                volume = volume.iloc[0]
            if volume < self.min_volume:
                return None  # existed, but too illiquid to trust the price

        return float(value)

    def strikes_available(self, date, expiry) -> list[float]:
        """All LIQUID strikes for this date+expiry (used to find the
        nearest valid strike to our target) -- illiquid strikes are
        excluded so we never pick a strike we can't get a real price for."""
        try:
            sub_close = self._close.loc[(date, expiry)]
        except KeyError:
            return []

        if self._volume is not None:
            sub_volume = self._volume.loc[(date, expiry)]
            liquid = sub_volume[sub_volume >= self.min_volume]
            return sorted(set(liquid.index.get_level_values("strike")))

        return sorted(set(sub_close.index.get_level_values("strike")))

    def expiries_available(self, date) -> list[pd.Timestamp]:
        """All expiries that had listed options on this date."""
        try:
            sub = self._close.loc[date]
        except KeyError:
            return []
        return sorted(set(sub.index.get_level_values("expiry")))


def nearest_strike(target: float, available_strikes: list[float]) -> float | None:
    """Snap a target strike price to the closest strike that's actually listed."""
    if not available_strikes:
        return None
    return min(available_strikes, key=lambda s: abs(s - target))
