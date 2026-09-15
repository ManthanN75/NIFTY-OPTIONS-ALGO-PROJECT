"""
STEP 1 of the pipeline: download raw daily files from NSE.

WHAT IS A "BHAVCOPY"?
----------------------
Every trading day, the National Stock Exchange (NSE) of India publishes an
official end-of-day (EOD) report of every trade that happened that day, for
every stock, index, future and option. This report is called the
"Bhavcopy" (bhav = price, copy = record, in Hindi/Marathi). It is free,
public, and is the same data brokers and exchanges themselves use.

We want the "Derivatives" bhavcopy, because Nifty options are derivatives
(their price is "derived" from the Nifty index). Each day's file is a
zipped CSV with one row per contract (every strike price, every expiry,
every option type, for every stock AND index that has options/futures).

WHAT THIS SCRIPT DOES
----------------------
For each trading day in a date range, it:
  1. Builds the URL where NSE hosts that day's derivatives bhavcopy.
  2. Downloads the .zip file.
  3. Unzips it in memory and saves the raw CSV to disk (in raw_data/).

We keep the RAW files on disk so that if a later step fails, we don't have
to re-download everything -- we can just re-clean the files we already have.

NSE sometimes has no file for a date (weekends, market holidays), and NSE's
website is picky about network requests that don't look like they came
from a real browser, so we add browser-like headers and retry a couple of
times before giving up on a given day.
"""

import io
import time
import zipfile
from datetime import date, timedelta
from pathlib import Path

import requests

RAW_DIR = Path(__file__).parent / "raw_data"

# NSE wants requests to look like they come from a normal web browser,
# otherwise it blocks them. This is not "hacking" anything -- it's the same
# public file a browser would download, we're just asking politely.
HEADERS = {
    "user-agent": (
        "Mozilla/5.0 (Windows NT 11.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/134.0.6998.166 Safari/537.36"
    ),
    "accept-encoding": "gzip, deflate",
}

# This is the URL pattern NSE uses (as of 2024 onwards) for the combined
# "UDiFF" derivatives bhavcopy, which includes stock AND index F&O together.
URL_TEMPLATE = (
    "https://nsearchives.nseindia.com/content/fo/"
    "BhavCopy_NSE_FO_0_0_0_{ymd}_F_0000.csv.zip"
)


def trading_day_candidates(start: date, end: date):
    """Every calendar day Mon-Fri between start and end (inclusive).

    We don't try to be clever about market holidays here -- it's simpler
    to just attempt every weekday and skip the ones that fail to download
    (holidays simply won't have a file on NSE's server, so they 404).
    """
    day = start
    while day <= end:
        if day.weekday() < 5:  # Monday=0 ... Friday=4
            yield day
        day += timedelta(days=1)


def download_one_day(session: requests.Session, day: date, dest_dir: Path,
                      retries: int = 2, pause: float = 1.0) -> Path | None:
    """Download and unzip one day's derivatives bhavcopy.

    Returns the path to the saved raw CSV, or None if that day had no data
    (e.g. a market holiday) or the download kept failing.
    """
    dest_dir.mkdir(parents=True, exist_ok=True)
    out_path = dest_dir / f"fo_bhav_{day:%Y%m%d}.csv"
    if out_path.exists():
        return out_path  # already downloaded, skip re-fetching

    url = URL_TEMPLATE.format(ymd=day.strftime("%Y%m%d"))

    for attempt in range(1, retries + 1):
        try:
            resp = session.get(url, timeout=20)
        except requests.RequestException as exc:
            print(f"  [{day}] network error (attempt {attempt}): {exc}")
            time.sleep(pause)
            continue

        if resp.status_code == 404:
            # Almost always means: market holiday / weekend, no file exists.
            return None

        if resp.status_code != 200:
            print(f"  [{day}] HTTP {resp.status_code} (attempt {attempt})")
            time.sleep(pause)
            continue

        try:
            with zipfile.ZipFile(io.BytesIO(resp.content)) as zf:
                name = zf.namelist()[0]
                csv_bytes = zf.read(name)
        except zipfile.BadZipFile:
            print(f"  [{day}] response wasn't a valid zip (attempt {attempt})")
            time.sleep(pause)
            continue

        out_path.write_bytes(csv_bytes)
        return out_path

    return None


def download_range(start: date, end: date, dest_dir: Path = RAW_DIR) -> list[Path]:
    """Download every available trading day's bhavcopy in [start, end]."""
    session = requests.Session()
    session.headers.update(HEADERS)

    saved_files = []
    days = list(trading_day_candidates(start, end))
    print(f"Attempting {len(days)} weekdays between {start} and {end} ...")

    for i, day in enumerate(days, 1):
        path = download_one_day(session, day, dest_dir)
        if path is not None:
            saved_files.append(path)
            print(f"  [{i}/{len(days)}] {day} -> {path.name}")
        else:
            print(f"  [{i}/{len(days)}] {day} -> skipped (holiday or no data)")
        # Be polite to NSE's server: small delay between requests.
        time.sleep(0.3)

    print(f"Done. Got {len(saved_files)} daily files out of {len(days)} weekdays.")
    return saved_files


if __name__ == "__main__":
    # Example: download the last 8 months up to today, when run directly.
    today = date.today()
    eight_months_ago = today - timedelta(days=8 * 30)
    download_range(eight_months_ago, today)
