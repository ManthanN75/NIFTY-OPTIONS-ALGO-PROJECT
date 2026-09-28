"""
Builds before_after_linkedin.png: the same 6-month test window, same
settings, run before and after the illiquid-price fix.

  before = test_trade_log.csv (saved from the run made before the fix)
  after  = the fixed engine, re-run here on test_data.csv
"""

import matplotlib.pyplot as plt
import pandas as pd
from matplotlib.ticker import FuncFormatter

from rust_bridge import run_account_backtest_rust
from strategy_config import EntryConfig, ExitConfig, StrategyConfig

START = 500_000.0
WINDOW_START = pd.Timestamp("2026-03-18")
WINDOW_END = pd.Timestamp("2026-09-11")

BEFORE_COLOR = "#d97706"
AFTER_COLOR = "#2563eb"
INK = "#1f2430"
MUTED = "#5f6675"
GRID = "#e6e8ec"
SURFACE = "#fcfcfb"

plt.rcParams["font.family"] = ["Segoe UI", "DejaVu Sans"]

before_log = pd.read_csv("test_trade_log.csv", parse_dates=["exit_date"])
test_df = pd.read_csv("test_data.csv", parse_dates=["date", "expiry"])
config = StrategyConfig(
    entry=EntryConfig(iv_threshold=80, iv_lookback_days=20),
    exit=ExitConfig(profit_target_pct=0.50),
)
after_log, _ = run_account_backtest_rust(test_df, config, START, 75)
after_log["exit_date"] = pd.to_datetime(after_log["exit_date"])


def curve(log):
    xs = [WINDOW_START] + list(log["exit_date"]) + [WINDOW_END]
    last = log["balance_after"].iloc[-1]
    ys = [START] + list(log["balance_after"]) + [last]
    return xs, ys, last


bx, by, before_final = curve(before_log)
ax_, ay, after_final = curve(after_log)
print("before final:", before_final, "trades:", len(before_log))
print("after final:", after_final, "trades:", len(after_log))

before_pnl = before_final - START
after_pnl = after_final - START


def fmt_rs(v):
    sign = "+" if v > 0 else "−"
    return f"{sign}₹{abs(round(v)):,}"


fig = plt.figure(figsize=(12, 6.27), dpi=100, facecolor=SURFACE)

fig.text(0.05, 0.92, "Same data. Same strategy. Same settings.", fontsize=25,
         fontweight="bold", color=INK, va="center")
fig.text(0.05, 0.855, "The only difference: one bug in how the backtest priced options.",
         fontsize=14, color=MUTED, va="center")

ax = fig.add_axes([0.075, 0.27, 0.60, 0.50], facecolor=SURFACE)
ax.step(bx, by, where="post", color=BEFORE_COLOR, linewidth=2.4, solid_capstyle="round")
ax.step(ax_, ay, where="post", color=AFTER_COLOR, linewidth=2.4, solid_capstyle="round")
ax.plot([bx[-1]], [by[-1]], "o", color=BEFORE_COLOR, markersize=8, markeredgecolor=SURFACE, markeredgewidth=2)
ax.plot([ax_[-1]], [ay[-1]], "o", color=AFTER_COLOR, markersize=8, markeredgecolor=SURFACE, markeredgewidth=2)
ax.axhline(START, color=MUTED, linewidth=1, linestyle=(0, (4, 4)), alpha=0.7)
ax.text(WINDOW_START, START + 1200, "starting balance", fontsize=10, color=MUTED, va="bottom")

ax.set_ylim(484_000, 570_000)
ax.set_xlim(WINDOW_START, WINDOW_END + pd.Timedelta(days=4))
ax.yaxis.set_major_formatter(FuncFormatter(lambda v, _: f"₹{v / 1e5:.1f}L"))
ax.grid(axis="y", color=GRID, linewidth=1)
ax.set_axisbelow(True)
for side in ("top", "right", "left"):
    ax.spines[side].set_visible(False)
ax.spines["bottom"].set_color(GRID)
ax.tick_params(colors=MUTED, labelsize=10.5, length=0)
ax.set_xticks(pd.to_datetime(["2026-04-01", "2026-05-01", "2026-06-01", "2026-07-01", "2026-08-01", "2026-09-01"]))
ax.set_xticklabels(["Apr", "May", "Jun", "Jul", "Aug", "Sep"])

# direct labels + legend swatches on the right
def label_block(y, color, title, pnl, note):
    fig.patches.append(plt.Rectangle((0.705, y - 0.004), 0.012, 0.012, transform=fig.transFigure,
                                     facecolor=color, edgecolor="none"))
    fig.text(0.725, y + 0.002, title, fontsize=12, color=MUTED, va="center")
    fig.text(0.705, y - 0.065, fmt_rs(pnl), fontsize=30, fontweight="bold", color=INK, va="center")
    fig.text(0.705, y - 0.125, note, fontsize=11, color=MUTED, va="center")


label_block(0.735, BEFORE_COLOR, "BEFORE THE FIX", before_pnl, f"{len(before_log)} trades, 80% win rate")
label_block(0.500, AFTER_COLOR, "AFTER THE FIX", after_pnl, f"{len(after_log)} trades, 33% win rate")

# the actual bug, in one box
box = fig.add_axes([0.05, 0.03, 0.90, 0.16], facecolor="#f1f2f5")
box.set_xticks([])
box.set_yticks([])
for s in box.spines.values():
    s.set_visible(False)
box.text(0.015, 0.80, "THE BUG", fontsize=10.5, fontweight="bold", color=MUTED, va="center", transform=box.transAxes)
box.text(0.015, 0.36,
         "A leg was priced 204.00 when I entered, and exactly 204.00 two days later. Volume that day: 0.\n"
         "Nobody traded it, but the backtest still booked profit on a price that didn't exist.",
         fontsize=12.5, color=INK, va="center", linespacing=1.5, transform=box.transAxes)

fig.text(0.95, 0.205, "Nifty iron condor backtest  ·  6-month test window  ·  IV rank > 80, 50% profit target, 2× stop",
         fontsize=9.5, color=MUTED, ha="right", va="center")

fig.savefig("before_after_linkedin.png", dpi=100, facecolor=SURFACE)
print("saved before_after_linkedin.png")
