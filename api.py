"""
FASTAPI BACKEND: serves the backtest results as JSON for a React frontend.

WHY THIS API DOESN'T ACCEPT PARAMETERS
------------------------------------------
You might expect an endpoint like `/api/backtest?iv_threshold=80&...` so
the frontend could let a user experiment with settings live. This API
deliberately does NOT do that for the tuning/test endpoints. The whole
point of test_data.csv (see README.md and evaluate_on_test.py) is that it
gets looked at with ONE fixed, already-committed set of settings -- if a
UI let you re-run the test period with different parameters, you'd
quietly turn it into more tuning data every time you clicked a slider,
and the "honest, unseen-data" result would stop meaning anything.

If you want an interactive "try different settings" UI, build it against
tuning_data.csv only (reusing grid_search.py's logic) -- that's the
correct place to experiment.

ENDPOINTS
-----------
  GET /api/health              -> {"status": "ok"}
  GET /api/tuning               -> metrics + trade log + equity curve (tuning period)
  GET /api/test                 -> metrics + trade log + equity curve (test period)
  GET /api/trades/{period}      -> just the trade log ("tuning" or "test")
  GET /api/equity-curve/{period}-> just the equity curve points ("tuning" or "test")

Every response is plain JSON (no NaN/Infinity -- those aren't valid JSON
and would break `fetch(...).json()` in the browser, so they're converted
to `null` first).

RUNNING IT
------------
    uvicorn api:app --reload

Then open http://127.0.0.1:8000/docs for interactive API docs (FastAPI
generates this automatically), or http://127.0.0.1:8000/api/tuning to see
raw JSON.
"""

from __future__ import annotations

import math
from contextlib import asynccontextmanager
from typing import Literal

import pandas as pd
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from evaluate_on_test import LOT_SIZE, STARTING_BALANCE, build_best_config
from performance_report import build_equity_curve, compute_performance_metrics
from rust_bridge import run_account_backtest_rust

Period = Literal["tuning", "test"]

# Filled in once at startup (see `lifespan` below) and served from memory
# after that -- the backtest is deterministic given the fixed settings, so
# there's no need to re-run it on every request.
_CACHE: dict[str, dict] = {}


def _sanitize(value):
    """Replace NaN/Infinity with None (JSON's `null`). Real JSON has no
    NaN/Infinity tokens -- a strict JS `JSON.parse` (which is what
    `fetch().json()` uses) will throw on them if Python's json module
    were left to emit them literally."""
    if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
        return None
    return value


def _trade_log_to_records(trade_log: pd.DataFrame) -> list[dict]:
    """Convert the trade log DataFrame into a list of plain JSON-safe dicts."""
    records = []
    for row in trade_log.to_dict(orient="records"):
        record = {}
        for key, value in row.items():
            if key in ("entry_date", "exit_date", "expiry"):
                record[key] = pd.Timestamp(value).date().isoformat()
            else:
                record[key] = _sanitize(value)
        records.append(record)
    return records


def _equity_curve_to_points(equity: pd.Series) -> list[dict]:
    """Convert the equity curve Series into [{date, balance}, ...] for charting."""
    return [
        {"date": pd.Timestamp(idx).date().isoformat(), "balance": _sanitize(float(value))}
        for idx, value in equity.items()
    ]


def _run_period(csv_path: str) -> dict:
    """Run the (Rust-backed) backtest on one CSV, using the already-committed
    settings from evaluate_on_test.py, and package up everything the
    frontend needs."""
    df = pd.read_csv(csv_path, parse_dates=["date", "expiry"])
    config = build_best_config()
    trade_log, _ = run_account_backtest_rust(df, config, STARTING_BALANCE, LOT_SIZE)
    metrics = compute_performance_metrics(trade_log, STARTING_BALANCE)
    equity = build_equity_curve(trade_log, STARTING_BALANCE)

    return {
        "metrics": {key: _sanitize(value) for key, value in metrics.items()},
        "trades": _trade_log_to_records(trade_log),
        "equity_curve": _equity_curve_to_points(equity),
    }


@asynccontextmanager
async def lifespan(app: FastAPI):
    _CACHE["tuning"] = _run_period("tuning_data.csv")
    _CACHE["test"] = _run_period("test_data.csv")
    yield
    _CACHE.clear()


app = FastAPI(title="Nifty Iron Condor Backtest API", lifespan=lifespan)

# Lets a React dev server (usually on localhost:3000 or 5173) call this
# API directly from the browser -- without this, the browser blocks the
# request as a cross-origin request (CORS).
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000", "http://127.0.0.1:3000",
        "http://localhost:5173", "http://127.0.0.1:5173",
    ],
    allow_methods=["GET"],
    allow_headers=["*"],
)


@app.get("/api/health")
def health():
    return {"status": "ok"}


@app.get("/api/tuning")
def tuning_results():
    """Metrics + trade log + equity curve for the tuning period (first 4 months)."""
    return _CACHE["tuning"]


@app.get("/api/test")
def test_results():
    """Metrics + trade log + equity curve for the test period (remaining
    ~6 months, unseen during tuning)."""
    return _CACHE["test"]


@app.get("/api/trades/{period}")
def trades(period: Period):
    """Just the full trade log for one period."""
    return _CACHE[period]["trades"]


@app.get("/api/equity-curve/{period}")
def equity_curve(period: Period):
    """Just the equity curve data points for one period -- ready to hand
    straight to a chart library in React (e.g. Recharts, Chart.js)."""
    return _CACHE[period]["equity_curve"]


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("api:app", host="127.0.0.1", port=8000, reload=True)
