"""
STEP 3 of the pipeline: split the cleaned data into two CSVs.

WHY WE SPLIT THE DATA
-----------------------
When you build/tune a trading strategy or model, you should never test it
on the same data you used to build it -- that's like grading your own exam
with the answer key you wrote. So we split time-wise:

  - tuning_data.csv   = the FIRST `tuning_months` months. Use this to
                        build, tweak, and tune your strategy or model.
  - test_data.csv     = EVERYTHING AFTER that. Only look at this AFTER
                        you've finalized your strategy, to see how it
                        performs on data it has never seen. This is
                        called "out-of-sample testing".

This project currently uses 10 months of data total: 4 months tuning,
6 months test (not an even 50/50 split) -- more out-of-sample months
gives a sturdier read on whether a strategy holds up, since the tuning
step above only ever produced 2-5 trades per setting on 4 months of data.

We split by calendar date (not just by row count), because each trading
day has a different number of option rows -- splitting by date keeps
whole days together and keeps the split easy to reason about.
"""

from __future__ import annotations

import pandas as pd
from pathlib import Path

OUTPUT_DIR = Path(__file__).parent

TUNING_MONTHS = 4  # the rest of the data (however many months are left) becomes test_data.csv


def split_by_date(df: pd.DataFrame, tuning_months: int = TUNING_MONTHS) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Split a DataFrame with a 'date' column: first `tuning_months` months
    of data -> tuning, everything after that -> test."""
    dates = df["date"]
    start = dates.min()
    cutoff = start + pd.DateOffset(months=tuning_months)

    tuning = df[df["date"] < cutoff].reset_index(drop=True)
    test = df[df["date"] >= cutoff].reset_index(drop=True)
    return tuning, test


def save_splits(df: pd.DataFrame, output_dir: Path = OUTPUT_DIR,
                 tuning_months: int = TUNING_MONTHS) -> tuple[Path, Path]:
    """Split the DataFrame and save tuning_data.csv / test_data.csv."""
    tuning, test = split_by_date(df, tuning_months)

    tuning_path = output_dir / "tuning_data.csv"
    test_path = output_dir / "test_data.csv"

    tuning.to_csv(tuning_path, index=False)
    test.to_csv(test_path, index=False)

    print(f"tuning_data.csv: {len(tuning)} rows, "
          f"{tuning['date'].min().date()} to {tuning['date'].max().date()}")
    print(f"test_data.csv:   {len(test)} rows, "
          f"{test['date'].min().date()} to {test['date'].max().date()}")

    return tuning_path, test_path
