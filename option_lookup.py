"""
FAST LOOKUPS: "what did THIS option cost on THIS day?"

During the backtest we constantly need to ask things like "what was the
23800 CE expiring 2026-03-31 worth on 2026-03-05?". Searching the whole
DataFrame with a filter every time would be slow (hundreds of thousands
of rows). So we build one lookup table, indexed by
(date, expiry, strike, option_type), once -- then every price lookup
afterwards is instant.
"""

from __future__ import annotations

import pandas as pd


class OptionPriceLookup:
    """Wraps the options DataFrame for fast (date, expiry, strike, type) -> close price lookups."""

    def __init__(self, df: pd.DataFrame):
        indexed = df.set_index(["date", "expiry", "strike", "option_type"]).sort_index()
        self._close = indexed["close"]

    def price(self, date, expiry, strike, option_type) -> float | None:
        """Return the closing price of one option contract, or None if it
        didn't trade / doesn't exist for that combination (e.g. a strike
        that wasn't listed, or a day the contract had zero trades)."""
        key = (date, expiry, strike, option_type)
        try:
            value = self._close.loc[key]
        except KeyError:
            return None
        # If duplicate rows ever slipped through, .loc could return a Series.
        if isinstance(value, pd.Series):
            value = value.iloc[0]
        return float(value)

    def strikes_available(self, date, expiry) -> list[float]:
        """All strikes that were listed for this date+expiry (used to find
        the nearest valid strike to our target)."""
        try:
            sub = self._close.loc[(date, expiry)]
        except KeyError:
            return []
        return sorted(set(sub.index.get_level_values("strike")))

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
