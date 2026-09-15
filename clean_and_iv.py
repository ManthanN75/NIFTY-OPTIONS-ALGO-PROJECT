"""
STEP 2 of the pipeline: turn raw daily CSVs into one clean pandas DataFrame,
and calculate Implied Volatility (IV) ourselves.

QUICK FINANCE PRIMER (for beginners)
-------------------------------------
An "option" is a contract that gives the right (not obligation) to buy or
sell the Nifty index at a fixed price (the "strike price") by a certain
date (the "expiry").

  - CE = Call option (right to BUY at the strike price). You'd want this
    if you think Nifty will go UP.
  - PE = Put option (right to SELL at the strike price). You'd want this
    if you think Nifty will go DOWN.

"Implied Volatility" (IV) is the market's guess of how much Nifty will
swing around (up or down) between now and expiry, expressed as a
percentage. It is "implied" because we don't observe it directly -- we
back-calculate it FROM the option's traded price, using a pricing formula
called Black-Scholes. Higher IV = market expects bigger moves = option is
more expensive, all else equal.

WHY WE CALCULATE IV OURSELVES
-------------------------------
NSE's historical bhavcopy files give us the option's closing PRICE, not its
IV. NSE's live option-chain webpage does show IV, but only for the current
moment -- there is no free historical IV feed. So this script solves the
Black-Scholes formula "backwards": given the price everyone agreed to pay
for the option, what volatility assumption would explain that price?

WHAT THIS SCRIPT DOES
-----------------------
1. Reads every raw CSV in raw_data/.
2. Filters down to just Nifty INDEX options (not stock options, not futures).
3. Renames/selects the columns we care about.
4. Cleans bad rows (missing prices, zero prices, expired-in-the-past rows).
5. Computes Implied Volatility for every row.
6. Returns one tidy DataFrame, sorted by date.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from pathlib import Path
from scipy.stats import norm

RAW_DIR = Path(__file__).parent / "raw_data"

# Assumed risk-free interest rate used in the Black-Scholes formula.
# This should roughly match the return on a "safe" investment like a
# government treasury bill. India's short-term T-bill rate has hovered
# around 6-7% in recent years, so 6.5% is a reasonable constant assumption
# for a beginner project (a more advanced version could look this up daily).
RISK_FREE_RATE = 0.065

TRADING_DAYS_PER_YEAR = 365  # calendar days, matches how NSE expiry is dated


def load_raw_files(raw_dir: Path = RAW_DIR) -> pd.DataFrame:
    """Read and concatenate every raw daily CSV into one big DataFrame."""
    files = sorted(raw_dir.glob("fo_bhav_*.csv"))
    if not files:
        raise FileNotFoundError(
            f"No raw bhavcopy CSVs found in {raw_dir}. "
            "Run download_bhavcopy.py first."
        )

    frames = []
    for f in files:
        df = pd.read_csv(f)
        frames.append(df)

    combined = pd.concat(frames, ignore_index=True)
    return combined


def filter_nifty_index_options(raw: pd.DataFrame) -> pd.DataFrame:
    """Keep only Nifty 50 INDEX options (drop stock options and futures)."""
    mask = (raw["TckrSymb"] == "NIFTY") & (raw["FinInstrmTp"] == "IDO")
    return raw.loc[mask].copy()


def select_and_rename(df: pd.DataFrame) -> pd.DataFrame:
    """Pick the columns we care about and give them friendly names."""
    out = df[[
        "TradDt", "XpryDt", "StrkPric", "OptnTp",
        "ClsPric", "UndrlygPric", "OpnIntrst", "TtlTradgVol",
    ]].rename(columns={
        "TradDt": "date",
        "XpryDt": "expiry",
        "StrkPric": "strike",
        "OptnTp": "option_type",
        "ClsPric": "close",
        "UndrlygPric": "underlying_close",
        "OpnIntrst": "open_interest",
        "TtlTradgVol": "volume",
    })
    out["date"] = pd.to_datetime(out["date"])
    out["expiry"] = pd.to_datetime(out["expiry"])
    return out


def clean_rows(df: pd.DataFrame) -> pd.DataFrame:
    """Drop rows that can't be valid trading data."""
    before = len(df)
    df = df.dropna(subset=["close", "strike", "underlying_close"])
    df = df[(df["close"] > 0) & (df["strike"] > 0) & (df["underlying_close"] > 0)]
    # Expiry must be on/after the trade date -- an option can't trade after it expired.
    df = df[df["expiry"] >= df["date"]]
    df = df.drop_duplicates(subset=["date", "strike", "option_type", "expiry"])
    after = len(df)
    print(f"clean_rows: kept {after}/{before} rows ({before - after} dropped)")
    return df.reset_index(drop=True)


# ---------------------------------------------------------------------------
# Black-Scholes implied volatility (vectorized Newton-Raphson solver)
# ---------------------------------------------------------------------------

def _bs_price(spot, strike, years_to_expiry, rate, sigma, is_call):
    """Black-Scholes theoretical option price, for arrays of inputs."""
    sigma = np.maximum(sigma, 1e-6)
    years_to_expiry = np.maximum(years_to_expiry, 1e-6)
    sqrt_t = np.sqrt(years_to_expiry)

    d1 = (np.log(spot / strike) + (rate + 0.5 * sigma ** 2) * years_to_expiry) / (sigma * sqrt_t)
    d2 = d1 - sigma * sqrt_t

    call_price = spot * norm.cdf(d1) - strike * np.exp(-rate * years_to_expiry) * norm.cdf(d2)
    put_price = strike * np.exp(-rate * years_to_expiry) * norm.cdf(-d2) - spot * norm.cdf(-d1)
    return np.where(is_call, call_price, put_price)


def _bs_vega(spot, strike, years_to_expiry, rate, sigma):
    """Vega = how much the option price changes per 1-unit change in
    volatility. Used to take Newton-Raphson steps towards the right IV."""
    sigma = np.maximum(sigma, 1e-6)
    years_to_expiry = np.maximum(years_to_expiry, 1e-6)
    sqrt_t = np.sqrt(years_to_expiry)
    d1 = (np.log(spot / strike) + (rate + 0.5 * sigma ** 2) * years_to_expiry) / (sigma * sqrt_t)
    return spot * norm.pdf(d1) * sqrt_t


def implied_volatility(spot, strike, years_to_expiry, rate, market_price, is_call,
                        max_iter: int = 60, tol: float = 1e-5) -> np.ndarray:
    """Solve for the volatility that makes Black-Scholes price == market price.

    This is done for every row at once (vectorized) using Newton-Raphson:
    start with a guess (30% volatility), see how wrong the resulting price
    is, and nudge the guess up/down using vega, repeating until the price
    error is tiny or we give up (in which case we report NaN for that row).
    """
    spot = np.asarray(spot, dtype=float)
    strike = np.asarray(strike, dtype=float)
    years_to_expiry = np.asarray(years_to_expiry, dtype=float)
    market_price = np.asarray(market_price, dtype=float)
    is_call = np.asarray(is_call, dtype=bool)

    sigma = np.full_like(market_price, 0.30)  # initial guess: 30% annualized vol
    converged = np.zeros_like(market_price, dtype=bool)

    for _ in range(max_iter):
        price_est = _bs_price(spot, strike, years_to_expiry, rate, sigma, is_call)
        diff = price_est - market_price
        newly_converged = np.abs(diff) < tol
        converged |= newly_converged

        vega = _bs_vega(spot, strike, years_to_expiry, rate, sigma)
        vega_safe = np.where(vega < 1e-8, 1e-8, vega)
        step = diff / vega_safe
        sigma = np.where(converged, sigma, sigma - step)
        sigma = np.clip(sigma, 1e-4, 5.0)  # keep within 0.01%-500% sane bounds

    sigma = np.where(converged, sigma, np.nan)
    # Also reject options with essentially no time left -- IV is meaningless there.
    sigma = np.where(years_to_expiry <= 1e-4, np.nan, sigma)
    return sigma


def add_implied_volatility(df: pd.DataFrame, rate: float = RISK_FREE_RATE) -> pd.DataFrame:
    """Add an 'implied_volatility' column (as a percentage, e.g. 14.5 = 14.5%)."""
    years_to_expiry = (df["expiry"] - df["date"]).dt.days / TRADING_DAYS_PER_YEAR
    is_call = df["option_type"] == "CE"

    iv = implied_volatility(
        spot=df["underlying_close"].to_numpy(),
        strike=df["strike"].to_numpy(),
        years_to_expiry=years_to_expiry.to_numpy(),
        rate=rate,
        market_price=df["close"].to_numpy(),
        is_call=is_call.to_numpy(),
    )
    df = df.copy()
    df["implied_volatility"] = iv * 100  # store as a percentage, e.g. 14.52
    return df


def build_clean_dataframe(raw_dir: Path = RAW_DIR) -> pd.DataFrame:
    """Run the full clean+IV pipeline and return the final DataFrame."""
    raw = load_raw_files(raw_dir)
    nifty = filter_nifty_index_options(raw)
    tidy = select_and_rename(nifty)
    tidy = clean_rows(tidy)
    tidy = add_implied_volatility(tidy)
    tidy = tidy.sort_values(["date", "expiry", "strike", "option_type"]).reset_index(drop=True)

    # Final column order, matching the spec: date, strike, option type,
    # expiry, close price, implied volatility (+ a couple of useful extras).
    tidy = tidy[[
        "date", "strike", "option_type", "expiry", "close",
        "implied_volatility", "underlying_close", "open_interest", "volume",
    ]]
    return tidy


if __name__ == "__main__":
    df = build_clean_dataframe()
    print(df.head())
    print(f"\nTotal rows: {len(df)}")
    print(f"Date range: {df['date'].min().date()} to {df['date'].max().date()}")
    pct_iv_missing = df["implied_volatility"].isna().mean() * 100
    print(f"Rows where IV could not be solved: {pct_iv_missing:.1f}%")
