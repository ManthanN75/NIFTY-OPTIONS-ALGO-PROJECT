"""
Builds ONE combined dataset covering the full ~24-month download window
(no tuning/test split) -- used for the post-liquidity-fix full-history
test in run_24m_backtest.py.

This is separate from run_pipeline.py (which downloads a window and
splits it into tuning_data.csv / test_data.csv) because this round is
deliberately NOT split: it's one continuous test of the strategy with its
already-chosen settings, across as much history as we have, now that the
illiquid-price bug is fixed. See run_24m_backtest.py for why.

Run download_range() for the ~24 month window FIRST (see
run_24m_backtest.py, which does this), then run this file to clean it.
"""

from __future__ import annotations

from clean_and_iv import build_clean_dataframe

OUTPUT_PATH = "data_24m.csv"


def build_and_save(output_path: str = OUTPUT_PATH):
    df = build_clean_dataframe()
    df.to_csv(output_path, index=False)
    print(f"{output_path}: {len(df)} rows, {df['date'].min().date()} to {df['date'].max().date()}")
    return df


if __name__ == "__main__":
    build_and_save()
