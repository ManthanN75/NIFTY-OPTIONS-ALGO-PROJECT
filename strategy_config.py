"""
ALL THE ADJUSTABLE KNOBS FOR THE IRON CONDOR STRATEGY.

Keeping every threshold in one place (as dataclasses) means you can tune
the strategy just by changing numbers here -- nothing else in the code
needs to change. Pass a different config into run_backtest() to try
different settings without editing the strategy logic itself.

WHAT IS AN IRON CONDOR?
-------------------------
It's a 4-leg options position that profits if Nifty stays roughly within a
range until expiry. You:
  1. SELL an out-of-the-money (OTM) Call  -> you collect premium, but if
     Nifty rallies a lot, you owe money on this leg.
  2. SELL an out-of-the-money (OTM) Put   -> you collect premium, but if
     Nifty falls a lot, you owe money on this leg.
  3. BUY a further OTM Call (above the sold call) -> this "hedge" caps
     your maximum possible loss if Nifty rallies hard.
  4. BUY a further OTM Put (below the sold put)    -> this "hedge" caps
     your maximum possible loss if Nifty falls hard.

You receive a net CREDIT (money) upfront when you open the position
(the two legs you sell are worth more than the two legs you buy, because
they're closer to the current price). Your best case is Nifty finishing
between the two SOLD strikes at expiry -- then all 4 options expire
worthless and you keep the whole credit. Your worst case is capped by the
hedges you bought.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class EntryConfig:
    """Rules for WHEN to open a new iron condor, and WHICH strikes/expiry to use."""

    # --- IV Rank / Percentile trigger ---
    # We enter when IV Rank (or Percentile, see `use_percentile`) CROSSES
    # ABOVE this level -- i.e. options just became relatively "expensive".
    iv_threshold: float = 60.0
    use_percentile: bool = False  # False = use IV Rank, True = use IV Percentile instead
    iv_lookback_days: int = 60    # how many past trading days IV Rank/Percentile looks at

    # --- Which expiry to trade ---
    target_dte: int = 30   # aim for an expiry roughly this many calendar days out
    min_dte: int = 14       # never enter something expiring sooner than this
    max_dte: int = 45       # never enter something expiring later than this

    # --- Where to place the strikes ---
    # Short strikes are placed this % away from the current Nifty price.
    # e.g. 0.03 = 3% out-of-the-money.
    short_call_otm_pct: float = 0.03
    short_put_otm_pct: float = 0.03
    # Long (hedge) strikes are placed this many Nifty POINTS further out
    # than the short strikes, e.g. 200 points beyond the short call/put.
    wing_width_points: float = 200.0
    # Nifty option strikes are only listed in steps of this size; we round
    # our target strike to the nearest valid one.
    strike_step: float = 50.0

    # --- Position sizing / limits ---
    max_concurrent_positions: int = 1  # keep it simple: only 1 open condor at a time


@dataclass
class ExitConfig:
    """Rules for WHEN to close an open iron condor."""

    # Take-profit: close once we've captured this % of the credit we
    # originally received. e.g. 0.50 = close once we've locked in 50% of
    # the max possible profit. (Taking partial profit early is common
    # practice -- squeezing out the last few % isn't usually worth the
    # extra days of risk.)
    profit_target_pct: float = 0.50

    # Stop-loss: close once our loss reaches this many TIMES the credit we
    # received. e.g. 2.0 = close once we've lost 2x the credit (so if we
    # collected 100 points of credit, we exit once we're down 200 points).
    stop_loss_multiple: float = 2.0

    # Forced time-based exit: always close this many days BEFORE expiry,
    # no matter what the P&L looks like. This avoids "expiry-day pin
    # risk" (option prices/greeks behaving erratically right at expiry).
    # 0 = allow holding all the way to expiry day itself.
    exit_days_before_expiry: int = 0


@dataclass
class StrategyConfig:
    """Bundles entry + exit rules together for convenience."""
    entry: EntryConfig
    exit: ExitConfig

    @classmethod
    def default(cls) -> "StrategyConfig":
        return cls(entry=EntryConfig(), exit=ExitConfig())
