// Rust port of run_account_backtest() from account_backtest.py.
//
// WHY DATES AND STRIKES ARE PLAIN INTEGERS HERE
// ------------------------------------------------
// Rust's PyO3 layer converts Python lists/ints/floats to native Rust types
// automatically, but pandas Timestamps and floats-as-dict-keys don't cross
// that boundary cleanly. So the Python side (rust_bridge.py) converts:
//   - every date -> an integer "ordinal" (days since a fixed reference date,
//     via Python's date.toordinal()) so dates are just comparable integers.
//   - every strike price -> "centi-rupees" (strike * 100, rounded to the
//     nearest whole number) so we can use exact integer keys instead of
//     floating-point keys (comparing floats for exact equality is unsafe).
// This file converts them back to real rupees only when computing money
// amounts (dividing by 100.0).

use pyo3::prelude::*;
use pyo3::types::PyDict;
use std::collections::{HashMap, HashSet};

#[derive(Clone)]
struct Position {
    entry_date: i64,
    expiry: i64,
    short_call_strike: i64, // centi-rupees
    short_put_strike: i64,
    long_call_strike: i64,
    long_put_strike: i64,
    entry_credit: f64, // Nifty points
}

/// Find the strike (from the strikes actually listed that day) closest to
/// our target strike. Mirrors option_lookup.nearest_strike() in Python.
fn nearest_strike(target: i64, strikes: &[i64]) -> Option<i64> {
    strikes.iter().min_by_key(|&&s| (s - target).abs()).copied()
}

/// Look up a leg's price, but ONLY if it actually traded that day (volume
/// >= min_volume). A contract nobody traded still has a "close" price in
/// NSE's bhavcopy -- it's just frozen/stale, not a real tradeable price --
/// so we treat it exactly like a missing price. This mirrors the fix in
/// option_lookup.OptionPriceLookup.price() (see that file's docstring for
/// the bug this fixes: illiquid, zero-volume legs were inflating win rate).
fn liquid_price(
    price_map: &HashMap<(i64, i64, i64, u8), f64>,
    volume_map: &HashMap<(i64, i64, i64, u8), i64>,
    min_volume: i64,
    key: (i64, i64, i64, u8),
) -> Option<f64> {
    let volume = *volume_map.get(&key)?;
    if volume < min_volume {
        return None;
    }
    price_map.get(&key).copied()
}

/// What it would cost to close the position today using TRADED prices.
/// Returns None if any of the 4 legs has no price today (illiquid day) --
/// mirrors iron_condor_backtest._cost_to_close_market().
fn cost_to_close_market(
    price_map: &HashMap<(i64, i64, i64, u8), f64>,
    volume_map: &HashMap<(i64, i64, i64, u8), i64>,
    min_volume: i64,
    date: i64,
    pos: &Position,
) -> Option<f64> {
    let sc = liquid_price(price_map, volume_map, min_volume, (date, pos.expiry, pos.short_call_strike, 0))?;
    let sp = liquid_price(price_map, volume_map, min_volume, (date, pos.expiry, pos.short_put_strike, 1))?;
    let lc = liquid_price(price_map, volume_map, min_volume, (date, pos.expiry, pos.long_call_strike, 0))?;
    let lp = liquid_price(price_map, volume_map, min_volume, (date, pos.expiry, pos.long_put_strike, 1))?;
    Some((sc + sp) - (lc + lp))
}

/// What it costs to close AT EXPIRY using intrinsic value (how NSE actually
/// cash-settles index options). Mirrors _cost_to_close_intrinsic().
fn cost_to_close_intrinsic(spot: f64, pos: &Position) -> f64 {
    let sc_strike = pos.short_call_strike as f64 / 100.0;
    let sp_strike = pos.short_put_strike as f64 / 100.0;
    let lc_strike = pos.long_call_strike as f64 / 100.0;
    let lp_strike = pos.long_put_strike as f64 / 100.0;

    let sc = (spot - sc_strike).max(0.0);
    let sp = (sp_strike - spot).max(0.0);
    let lc = (spot - lc_strike).max(0.0);
    let lp = (lp_strike - spot).max(0.0);
    (sc + sp) - (lc + lp)
}

/// Try to build a valid iron condor for today. Mirrors
/// iron_condor_backtest.try_enter_iron_condor().
#[allow(clippy::too_many_arguments)]
fn try_enter_iron_condor(
    date: i64,
    spot: f64,
    price_map: &HashMap<(i64, i64, i64, u8), f64>,
    volume_map: &HashMap<(i64, i64, i64, u8), i64>,
    min_volume: i64,
    strikes_by_date_expiry: &HashMap<(i64, i64), Vec<i64>>,
    expiries_by_date: &HashMap<i64, Vec<i64>>,
    short_call_otm_pct: f64,
    short_put_otm_pct: f64,
    wing_width_points: f64,
    target_dte: i64,
    min_dte: i64,
    max_dte: i64,
) -> Option<Position> {
    // Step 1: pick the expiry closest to target_dte, within [min_dte, max_dte].
    let expiries = expiries_by_date.get(&date)?;
    let mut best: Option<(i64, i64)> = None; // (expiry, |dte - target_dte|)
    for &exp in expiries {
        let dte = exp - date;
        if dte >= min_dte && dte <= max_dte {
            let diff = (dte - target_dte).abs();
            match best {
                Some((_, best_diff)) if diff >= best_diff => {}
                _ => best = Some((exp, diff)),
            }
        }
    }
    let expiry = best.map(|(exp, _)| exp)?;

    let strikes = strikes_by_date_expiry.get(&(date, expiry))?;
    if strikes.is_empty() {
        return None;
    }

    // Step 2: short strikes = target % OTM from spot, snapped to a real strike.
    let raw_short_call = (spot * (1.0 + short_call_otm_pct) * 100.0).round() as i64;
    let raw_short_put = (spot * (1.0 - short_put_otm_pct) * 100.0).round() as i64;
    let short_call_strike = nearest_strike(raw_short_call, strikes)?;
    let short_put_strike = nearest_strike(raw_short_put, strikes)?;

    // Step 3: long (hedge) strikes = wing_width_points further out.
    let wing_centi = (wing_width_points * 100.0).round() as i64;
    let long_call_strike = nearest_strike(short_call_strike + wing_centi, strikes)?;
    let long_put_strike = nearest_strike(short_put_strike - wing_centi, strikes)?;

    // Sanity check: hedges must be strictly further out than the shorts.
    if !(long_call_strike > short_call_strike && long_put_strike < short_put_strike) {
        return None;
    }

    let sc_price = liquid_price(price_map, volume_map, min_volume, (date, expiry, short_call_strike, 0))?;
    let sp_price = liquid_price(price_map, volume_map, min_volume, (date, expiry, short_put_strike, 1))?;
    let lc_price = liquid_price(price_map, volume_map, min_volume, (date, expiry, long_call_strike, 0))?;
    let lp_price = liquid_price(price_map, volume_map, min_volume, (date, expiry, long_put_strike, 1))?;

    let entry_credit = (sc_price + sp_price) - (lc_price + lp_price);
    if entry_credit <= 0.0 {
        return None; // would be a net debit -- skip, same as the Python version
    }

    Some(Position {
        entry_date: date,
        expiry,
        short_call_strike,
        short_put_strike,
        long_call_strike,
        long_put_strike,
        entry_credit,
    })
}

/// The main entry point called from Python. Runs the whole day-by-day loop.
///
/// All the option rows are passed in as 5 parallel lists (one entry per
/// row: date, expiry, strike, option_type, close price) instead of a
/// DataFrame, because that's the simplest thing to hand across the
/// Python/Rust boundary. This function rebuilds the same lookup structures
/// that option_lookup.py builds in Python, just using Rust's HashMap.
#[pyfunction]
#[allow(clippy::too_many_arguments)]
fn run_account_backtest_rs(
    py: Python<'_>,
    trading_days: Vec<i64>,
    opt_dates: Vec<i64>,
    opt_expiries: Vec<i64>,
    opt_strikes_centi: Vec<i64>,
    opt_types: Vec<u8>, // 0 = CE, 1 = PE
    opt_closes: Vec<f64>,
    opt_volumes: Vec<i64>,
    min_volume: i64,
    spot_dates: Vec<i64>,
    spot_values: Vec<f64>,
    signal_dates: Vec<i64>,
    signal_values: Vec<f64>,
    iv_threshold: f64,
    short_call_otm_pct: f64,
    short_put_otm_pct: f64,
    wing_width_points: f64,
    target_dte: i64,
    min_dte: i64,
    max_dte: i64,
    profit_target_pct: f64,
    stop_loss_multiple: f64,
    exit_days_before_expiry: i64,
    starting_balance: f64,
    lot_size: f64,
) -> PyResult<(Vec<Py<PyDict>>, f64)> {
    // --- Rebuild the lookup tables (same shape as option_lookup.py's) ---
    let mut price_map: HashMap<(i64, i64, i64, u8), f64> = HashMap::new();
    let mut volume_map: HashMap<(i64, i64, i64, u8), i64> = HashMap::new();
    let mut strikes_set: HashMap<(i64, i64), HashSet<i64>> = HashMap::new();
    let mut expiries_set: HashMap<i64, HashSet<i64>> = HashMap::new();

    for i in 0..opt_dates.len() {
        let key = (opt_dates[i], opt_expiries[i], opt_strikes_centi[i], opt_types[i]);
        price_map.insert(key, opt_closes[i]);
        volume_map.insert(key, opt_volumes[i]);

        // Only offer up a strike as a candidate to trade if it actually
        // traded that day -- mirrors option_lookup.strikes_available()'s
        // liquidity filter in the Python version.
        if opt_volumes[i] >= min_volume {
            strikes_set
                .entry((opt_dates[i], opt_expiries[i]))
                .or_insert_with(HashSet::new)
                .insert(opt_strikes_centi[i]);
        }

        expiries_set
            .entry(opt_dates[i])
            .or_insert_with(HashSet::new)
            .insert(opt_expiries[i]);
    }

    // Sort each strike list ascending -- Rust's HashSet has no defined
    // iteration order (it can even differ between runs of the same
    // program), so without sorting, a tie in nearest_strike() (two
    // strikes equally close to the target) could resolve differently
    // than the Python engine, or even differently run to run. Sorting
    // makes tie-breaking deterministic and matches Python's behavior
    // (option_lookup.py builds its strike lists via sorted(set(...))).
    let strikes_by_date_expiry: HashMap<(i64, i64), Vec<i64>> = strikes_set
        .into_iter()
        .map(|(k, v)| {
            let mut strikes: Vec<i64> = v.into_iter().collect();
            strikes.sort_unstable();
            (k, strikes)
        })
        .collect();
    let expiries_by_date: HashMap<i64, Vec<i64>> = expiries_set
        .into_iter()
        .map(|(k, v)| (k, v.into_iter().collect()))
        .collect();

    let spot_map: HashMap<i64, f64> = spot_dates.into_iter().zip(spot_values).collect();
    let signal_map: HashMap<i64, f64> = signal_dates.into_iter().zip(signal_values).collect();

    // --- The actual day-by-day simulation loop ---
    let mut sorted_days = trading_days;
    sorted_days.sort_unstable();
    sorted_days.dedup();

    let mut balance = starting_balance;
    let mut open_position: Option<Position> = None;
    let mut prev_signal: Option<f64> = None;
    let mut trades: Vec<Py<PyDict>> = Vec::new();

    for date in sorted_days {
        let spot = spot_map.get(&date).copied();

        // --- Step 1: manage an open position (mark to market, check exits) ---
        if let Some(pos) = open_position.clone() {
            let dte_remaining = pos.expiry - date;
            let forced_expiry_exit = dte_remaining <= exit_days_before_expiry;

            let mut exit_cost: Option<f64> = None;
            let mut reason: Option<&str> = None;

            if forced_expiry_exit {
                if let Some(s) = spot {
                    exit_cost = Some(cost_to_close_intrinsic(s, &pos));
                    reason = Some("expiry");
                }
            } else {
                exit_cost = cost_to_close_market(&price_map, &volume_map, min_volume, date, &pos);
                if let Some(ec) = exit_cost {
                    let pnl_now = pos.entry_credit - ec;
                    if pnl_now >= profit_target_pct * pos.entry_credit {
                        reason = Some("profit_target");
                    } else if pnl_now <= -stop_loss_multiple * pos.entry_credit {
                        reason = Some("stop_loss");
                    }
                }
            }

            if let (Some(ec), Some(r)) = (exit_cost, reason) {
                let pnl_points = pos.entry_credit - ec;
                let pnl_rupees = pnl_points * lot_size;
                let premium_rupees = pos.entry_credit * lot_size;
                balance += pnl_rupees;

                let dict = PyDict::new_bound(py);
                dict.set_item("entry_date", pos.entry_date)?;
                dict.set_item("exit_date", date)?;
                dict.set_item("expiry", pos.expiry)?;
                dict.set_item("short_call_strike", pos.short_call_strike as f64 / 100.0)?;
                dict.set_item("short_put_strike", pos.short_put_strike as f64 / 100.0)?;
                dict.set_item("long_call_strike", pos.long_call_strike as f64 / 100.0)?;
                dict.set_item("long_put_strike", pos.long_put_strike as f64 / 100.0)?;
                dict.set_item("premium_collected_points", pos.entry_credit)?;
                dict.set_item("premium_collected_rupees", premium_rupees)?;
                dict.set_item("exit_cost_points", ec)?;
                dict.set_item("pnl_points", pnl_points)?;
                dict.set_item("pnl_rupees", pnl_rupees)?;
                dict.set_item("exit_reason", r)?;
                dict.set_item("balance_after", balance)?;
                trades.push(dict.unbind());

                open_position = None;
            }
        }

        // --- Step 2: look for a fresh entry signal (only when flat) ---
        let current_signal = signal_map.get(&date).copied();
        if open_position.is_none() {
            if let (Some(cur), Some(prev)) = (current_signal, prev_signal) {
                let crossed_above = prev < iv_threshold && iv_threshold <= cur;
                if crossed_above {
                    if let Some(s) = spot {
                        open_position = try_enter_iron_condor(
                            date,
                            s,
                            &price_map,
                            &volume_map,
                            min_volume,
                            &strikes_by_date_expiry,
                            &expiries_by_date,
                            short_call_otm_pct,
                            short_put_otm_pct,
                            wing_width_points,
                            target_dte,
                            min_dte,
                            max_dte,
                        );
                    }
                }
            }
        }

        if let Some(cur) = current_signal {
            prev_signal = Some(cur);
        }
    }

    Ok((trades, balance))
}

#[pymodule]
fn nifty_backtest_rs(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_function(wrap_pyfunction!(run_account_backtest_rs, m)?)?;
    Ok(())
}
