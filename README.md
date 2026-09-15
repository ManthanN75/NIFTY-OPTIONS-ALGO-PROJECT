# Nifty Options Data Pipeline (for beginners)

This project downloads 8 months of historical Nifty **index options** data
for free from NSE, cleans it up, calculates Implied Volatility, and splits
it into a `tuning_data.csv` (first 4 months) and `test_data.csv` (last 4
months) that you can use to build and test a trading strategy or model.

## 1. Some finance basics first

- **Nifty 50** is India's main stock market index — basically a single
  number that tracks the average performance of the 50 biggest companies
  listed on NSE.
- An **option** is a contract, not a stock. It gives you the *right* (but
  not the obligation) to buy or sell the Nifty index at a fixed price (the
  **strike price**) on or before a fixed date (the **expiry**).
  - **CE (Call)** = right to **buy** at the strike. You'd want this if you
    think Nifty is going **up**.
  - **PE (Put)** = right to **sell** at the strike. You'd want this if you
    think Nifty is going **down**.
- The **close price** is what the option last traded for that day — this
  is the "cost" of the option contract.
- **Implied Volatility (IV)** is the market's built-in guess of how much
  Nifty will swing up or down before expiry, shown as a %. It isn't
  published directly anywhere for historical data — we calculate
  ("imply") it ourselves from the close price using a formula called
  **Black-Scholes** (explained more below). Higher IV = market expects
  bigger swings = option costs more.
- **Bhavcopy** is NSE's official free daily report of every trade. It's
  the source of all the raw data here.

## 2. Where the data comes from

NSE publishes a free daily "Derivatives Bhavcopy" file (no login, no paid
API) at a public URL. It contains every stock and index future/option
traded that day. We download it, then keep only the rows where the symbol
is `NIFTY` and the instrument type is "Index Options".

Two libraries are commonly recommended for this (`nsepython`,
`jugaad-data`), but at the time of building this, NSE had changed its file
format and neither library's option-download function was working. So
this project talks to NSE's public file server directly using the same
approach those libraries use under the hood (`requests` + browser-like
headers) — this was tested and confirmed working.

## 3. Why we calculate IV ourselves

Historical bhavcopy files give us the option's **price**, not its IV. IV
only shows up on NSE's *live* option-chain webpage, which only shows
"right now" — there's no free historical IV feed. So we reverse-engineer
it: Black-Scholes normally goes `(strike, spot price, time left, interest
rate, volatility) → option price`. We plug in everything we know (strike,
spot, time left, price) and solve backwards for the one unknown:
volatility. This is exactly what NSE's own website and every broker
platform do — there's nothing unusual about it, it's standard practice.

**A note on data quality:** for some options — usually deep
in-the-money options very close to expiry — the calculated IV will be
missing (`NaN`). This happens when the option's last traded price and the
index's final closing price were recorded at very slightly different
moments during the day, making the numbers briefly inconsistent with the
pricing formula. This is a normal quirk of free end-of-day data, not a
bug — expect roughly 15-25% of rows to have a missing IV, concentrated in
these edge cases.

## 4. Files in this project

| File | What it does |
|---|---|
| `download_bhavcopy.py` | Downloads raw daily NSE files into `raw_data/` |
| `clean_and_iv.py` | Cleans the raw data, filters to Nifty options, calculates IV |
| `split_and_save.py` | Splits the cleaned data by date into two CSVs |
| `run_pipeline.py` | Runs all three steps in order — **this is the one you run** |
| `raw_data/` | Cache of raw downloaded files (so re-runs are fast) |
| `tuning_data.csv` | Output: first ~4 months of cleaned data |
| `test_data.csv` | Output: last ~4 months of cleaned data |

## 5. How to run it

```bash
pip install -r requirements.txt
python run_pipeline.py
```

This will take a while — it's about 170 individual daily downloads for 8
months of trading days, with a small polite delay between each so we don't
hammer NSE's server. If you re-run it later, previously downloaded days in
`raw_data/` are reused automatically, so it'll be much faster the second
time.

When it finishes, you'll have `tuning_data.csv` and `test_data.csv` in
this folder with these columns:

| Column | Meaning |
|---|---|
| `date` | The trading day |
| `strike` | The strike price of the option |
| `option_type` | `CE` (call) or `PE` (put) |
| `expiry` | The date the option contract expires |
| `close` | The option's closing (last traded) price that day |
| `implied_volatility` | Our calculated IV, as a percentage |
| `underlying_close` | Nifty index's closing value that day (used to calculate IV) |
| `open_interest` | Number of open (not yet closed) contracts — a popularity/liquidity signal |
| `volume` | Number of contracts traded that day |

## 6. Why the tuning/test split

If you build a strategy and only ever test it on the same data you built
it with, you'll fool yourself into thinking it works better than it
really does (this is called **overfitting**). So:

- Use `tuning_data.csv` (the older 4 months) to build and adjust your
  strategy or model.
- Only run it once, at the end, on `test_data.csv` (the newer 4 months)
  to get an honest read on how it would have performed on data it never
  saw during development.

## 7. Customizing

- Change the date range: edit `months_back` in `run_pipeline.py`'s
  `main()` function, or call `download_range(start_date, end_date)` from
  `download_bhavcopy.py` directly with your own dates.
- Change the assumed risk-free interest rate used in the IV calculation:
  edit `RISK_FREE_RATE` in `clean_and_iv.py`.
