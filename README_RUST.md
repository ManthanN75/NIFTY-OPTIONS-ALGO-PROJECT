# Running the backtest loop in Rust (PyO3 setup, step by step)

This ports the day-by-day loop from `account_backtest.py`'s
`run_account_backtest()` into Rust, so it runs as compiled machine code
instead of interpreted Python. Everything else (reading the CSV,
calculating IV rank) still happens in Python — only the actual
entry/exit simulation loop moved to Rust.

**Status: built and verified.** This has been compiled and its output
checked against the pure-Python version on `tuning_data.csv` — both
produce identical trades and the same final balance.

## 1. What PyO3 actually is

PyO3 is a Rust library ("crate") that lets Rust code define functions
Python can call as if they were normal Python functions, and lets Rust
read/write Python objects (lists, dicts, numbers). `maturin` is the build
tool that compiles your Rust code into a `.pyd` file (Windows' version of
a Python extension module) and drops it straight into your Python
environment — so `import nifty_backtest_rs` just works afterward, no
manual copying of files.

## 2. One-time setup

**Install Rust** (if you don't have it): go to https://rustup.rs and run
the installer it gives you. Restart your terminal afterward. Check it worked:

```bash
rustc --version
cargo --version
```

**Why you need a virtual environment (venv) here.** `maturin develop`
doesn't just compile the Rust code — it installs the result directly into
a Python environment, and it insists on that being a proper venv (not
just "whichever `python.exe` happens to run"). On this machine, `python`
and `pip` also aren't on the Windows PATH at all — only the full path to
`python.exe` works — so a venv fixes both problems at once, and gives you
a clean `python`/`pip` you can call by name after activating it.

A venv called `.venv` has already been created in the project root. From
a fresh terminal, activate it first — you'll need to do this every time
you open a new terminal to work on this project:

```bash
"C:\Users\manth\Downloads\NIFTY OPTIONS ALGO PROJECT\.venv\Scripts\activate.bat"
```

(In PowerShell specifically, use `.venv\Scripts\Activate.ps1` instead.)

Once activated, your prompt will show `(.venv)` at the start, and `python`,
`pip`, and `maturin` all resolve correctly without needing full paths.
Install the project's dependencies plus maturin into it (only needed once):

```bash
pip install maturin pandas numpy scipy requests
```

If you ever see `'python' is not recognized...` again, it means the venv
isn't activated in that terminal — just re-run the activate command above.

## 3. The project layout

I've already created this structure under `nifty_backtest_rs/`:

```
nifty_backtest_rs/
├── Cargo.toml       <- Rust package metadata + dependencies (pyo3)
├── pyproject.toml   <- tells maturin this is a Python-extension project
└── src/
    └── lib.rs       <- the actual Rust code (the ported loop)
```

You don't need to create anything — just review `src/lib.rs` if you're curious.

## 4. Build it

With the venv activated (see step 2), from inside the `nifty_backtest_rs/` folder:

```bash
cd nifty_backtest_rs
maturin develop --release
```

`maturin develop` compiles the Rust code and installs it directly into
your currently-active Python environment (like `pip install -e .` but for
a Rust extension) — that's why the venv has to be activated first, so
maturin knows exactly where to install it. `--release` turns on compiler
optimizations — always use it for anything you're actually timing/using,
since a debug build can be 10-20x slower.

The first build takes a little while (it also compiles the `pyo3`
dependency itself, from scratch). You should see `Installed
nifty_backtest_rs-0.1.0` at the end.

**A version snag we hit and fixed:** the crate originally pinned
`pyo3 = "0.20.3"`, which doesn't support Python 3.13 and fails with
`the configured Python interpreter version (3.13) is newer than PyO3's
maximum supported version (3.12)`. `Cargo.toml` now pins `pyo3 = "0.22"`
instead, and `src/lib.rs` uses that version's current `Bound<'_, T>` API
(e.g. `PyDict::new_bound(py)`, `#[pymodule] fn ...(m: &Bound<'_, PyModule>)`).
If you're on an older Python (3.12 or earlier), this newer pyo3 still
works fine — no need to downgrade anything.

## 5. Use it from Python

Go back to the project root folder and run:

```bash
cd ..
python rust_bridge.py
```

`rust_bridge.py` does the pandas/IV-rank prep in Python (unchanged), then
calls `nifty_backtest_rs.run_account_backtest_rs(...)` — the compiled Rust
function — for the actual simulation loop, and turns the result back into
a normal pandas DataFrame.

You can also call it directly in your own scripts:

```python
import pandas as pd
from rust_bridge import run_account_backtest_rust
from strategy_config import StrategyConfig

df = pd.read_csv("tuning_data.csv", parse_dates=["date", "expiry"])
trade_log, final_balance = run_account_backtest_rust(df, StrategyConfig.default())
```

## 6. Checking it matches the Python version

Since this is meant to be a faster drop-in replacement, sanity-check that
both versions agree before trusting the Rust one for anything important:

```python
import pandas as pd
from strategy_config import StrategyConfig
from account_backtest import run_account_backtest
from rust_bridge import run_account_backtest_rust

df = pd.read_csv("tuning_data.csv", parse_dates=["date", "expiry"])
cfg = StrategyConfig.default()
cfg.entry.iv_lookback_days = 20
cfg.entry.iv_threshold = 50.0

py_trades, py_balance = run_account_backtest(df, cfg)
rs_trades, rs_balance = run_account_backtest_rust(df, cfg)

print("Python final balance:", py_balance)
print("Rust final balance:  ", rs_balance)
print(py_trades)
print(rs_trades)
```

They should produce identical trades and identical final balances — this
was run for real on `tuning_data.csv` and confirmed matching (3 trades,
final balance Rs 5,42,843.75 both ways).

## 7. If something goes wrong

- `'python'`/`'pip'`/`'maturin' is not recognized`: your venv isn't
  activated in this terminal. Run the `activate.bat` command from step 2
  again — you need to do this in every new terminal window.
- `maturin develop` fails with `Couldn't find a virtualenv or conda
  environment`: same root cause — activate `.venv` first.
- `maturin develop` fails to compile: copy the full error and send it to
  me — Rust's compiler errors are verbose but usually point at an exact
  line and reason.
- `import nifty_backtest_rs` fails with `ModuleNotFoundError`: you likely
  ran `maturin develop` in a different terminal/environment than the one
  you're now running `python` from. Activate `.venv`, then re-run
  `maturin develop --release` from inside `nifty_backtest_rs/`.
- Results don't match the Python version: check step 6 above first — that
  comparison will tell you exactly which trade started diverging.

## 8. Why it's faster

Every call in the Python loop — dictionary lookups, `.loc[]` on pandas
data, attribute access on dataclasses — carries interpreter overhead.
Rust compiles straight to machine code with no such overhead, and the
lookup tables here are plain Rust `HashMap`s instead of pandas-backed
structures. For a small ~80-day backtest the difference won't be
noticeable, but it matters once you're testing years of data or running
many parameter combinations (e.g. tuning threshold values by brute force).
