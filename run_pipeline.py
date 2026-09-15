"""
MAIN ENTRY POINT: runs the whole Nifty options data pipeline end-to-end.

    python run_pipeline.py

This will:
  1. Download ~10 months of daily NSE derivatives bhavcopy files
     (download_bhavcopy.py) into raw_data/.
  2. Clean them into one DataFrame and calculate Implied Volatility for
     every row (clean_and_iv.py).
  3. Split the result into tuning_data.csv (first 4 months) and
     test_data.csv (remaining ~6 months) (split_and_save.py).

10 months / 4-tuning / 6-test is a deliberate choice (not an even split):
4 months is enough to search a parameter grid, and 6 months of untouched
test data gives a sturdier out-of-sample read than the 4/4 split we used
before -- our tuning grid only ever produced 2-5 trades per setting on 4
months of data, so more test months matters more than more tuning months.

See the README.md for a plain-English explanation of every step and every
financial term used here.
"""

from datetime import date, timedelta

from download_bhavcopy import download_range
from clean_and_iv import build_clean_dataframe
from split_and_save import save_splits, TUNING_MONTHS


def main(months_back: int = 10, tuning_months: int = TUNING_MONTHS):
    today = date.today()
    # Yesterday, because today's bhavcopy usually isn't published until
    # evening, and using "today" could give us an empty/partial day.
    end_date = today - timedelta(days=1)
    start_date = end_date - timedelta(days=months_back * 30)

    print("=" * 70)
    print(f"STEP 1/3: Downloading raw bhavcopy files ({start_date} to {end_date})")
    print("=" * 70)
    download_range(start_date, end_date)

    print("\n" + "=" * 70)
    print("STEP 2/3: Cleaning data + calculating Implied Volatility")
    print("=" * 70)
    df = build_clean_dataframe()
    print(df.head())
    print(f"Total cleaned rows: {len(df)}")

    print("\n" + "=" * 70)
    print(f"STEP 3/3: Splitting into tuning_data.csv (first {tuning_months} months) "
          f"/ test_data.csv (remaining months)")
    print("=" * 70)
    save_splits(df, tuning_months=tuning_months)

    print("\nDone! Files are in this folder: tuning_data.csv, test_data.csv")


if __name__ == "__main__":
    main()
