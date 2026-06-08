# cheap-entry-methodology-sim

Offline Monte-Carlo backtests for a cheap-entry Polymarket strategy, with permutation significance, an M1-veto overlay, and fire-selection sweeps.

The live bot's significant strategies all entered expensive ($0.69-$0.85), capping per-win payoff. These sims test the inverse: any positive-EV strategy, but only on entries at or below $0.50, where a win pays `1/price - 1`. Each script measures whether that survives a permutation test and how it grows a $9 bankroll toward $100.

## Pipeline

Each script is standalone. It globs Polymarket 5-minute BTC up/down race-replay logs, regex-parses fire lines (`strategy / side / entry price / cd`) and the `MARKET RECAP ... (winner=...)` line, builds a per-strategy EV table, then bootstrap-resamples market sequences under a tiered ruin guard (PAUSE/HALT thresholds, balance-tiered fire cap). Fires with `cd <= 15` are dropped. Seeded `random`; output is summary tables to stdout, no files written.

## Scripts

- `sim_cheap_entries.py`: positive-EV strategies + entry <= $0.50, fixed $1 fire, PAUSE $7. Reports coverage, methodology `p_perm` (PnL vs 1000 winner-shuffles), and a 2000-run MC per entry cap.
- `sim_cheap_v2.py`: small fixed fire sizing ($0.25/$0.50) with PAUSE set just above HALT so one loss cannot wipe. Sweeps entry-cap x fire-size x cap; ranks top cheap-zone strategies by EV.
- `sim_cheap_m1.py`: adds the M1 veto, a per-fire probabilistic block calibrated from the 535-market shadow predictor (blocks 58% of losers, 23.4% of winners). Compares M1 OFF vs ON across configs.
- `sim_fire_selection.py`: fixes the strategy set to the 4 `p_perm < 0.05` edges (`t4_ext`, `early_up_collapse_dn`, `t6_early`, `t4_late`) and compares selection rules: FIFO, highest-EV, highest-WR, cheapest, most-expensive.
- `sim_methodology.py`: searches for the fastest $9 to $100 at 0% wipe across strategy pools (EV>0 / >$0.05 / >$0.10 / large-sample) x selectors x sizing (fixed / adaptive / kelly-lite) x low-tier cap.

## Requirements

Python 3.8+, standard library only. No pip, no virtualenv. Read-only; no wallet, key, or network access.

## Usage

```bash
python3 sim_cheap_entries.py
python3 sim_cheap_v2.py
python3 sim_cheap_m1.py
python3 sim_fire_selection.py
python3 sim_methodology.py
```

## Data

Logs are loaded from the hard-coded glob `$DATA_DIR/quant_bots_logs_replay/race_test_btc-updown-5m-*.log`. Not committed (see `.gitignore`); fetch from the private `polymarket-data` repo and place at that path or edit `PATH_PATTERN` at the top of each file. Up to 500 logs are sampled (seeded) per run.
