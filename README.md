# cheap-entry-methodology-sim

Cheap-entry methodology backtests for Polymarket with permutation significance, M1-veto overlay, and fire-selection exploration.

## Why it exists

The live bot's statistically-significant strategies all entered on the **expensive** side ($0.69–$0.85), leaving asymmetric payoff on the table. This repo tests the inverse thesis: take **any** positive-EV strategy but only on **cheap entries (≤ $0.50)**, where a win pays `1/price − 1`. It answers, offline and rigorously, whether that methodology survives a permutation test and how fast/safely it grows a small ($9) bankroll to $100.

## How it works

Each script is a standalone Monte-Carlo simulator over **Polymarket 5-minute BTC up/down** race-replay logs. They share the same pipeline: regex-parse fire lines (`strategy / side / entry price / cd`) and the `MARKET RECAP ... (winner=...)` line out of each log, build a per-strategy EV table, then bootstrap-resample market sequences under a tiered ruin guard (PAUSE/HALT thresholds, balance-tiered fire cap).

| Script | What it explores |
| --- | --- |
| `sim_cheap_entries.py` | Core thesis: positive-EV strategies + entry ≤ $0.50, fixed $1 fire, PAUSE $7. Reports coverage, **methodology-level `p_perm`** (PnL vs 1000 winner-shuffles), and a 2000-run MC per entry cap. |
| `sim_cheap_v2.py` | Same thesis with **small fixed fire sizing** ($0.25/$0.50) and PAUSE set just above HALT so one loss can't wipe. Sweeps entry-cap × fire-size × cap combos; prints top cheap-zone strategies by EV. |
| `sim_cheap_m1.py` | Overlays the **M1 veto** (probabilistic per-fire block calibrated from the 535-mkt shadow predictor: ~58% of losers, ~23% of winners blocked) and compares M1 OFF vs ON across configs. |
| `sim_fire_selection.py` | Holds strategy set fixed to the **4 `p_perm < 0.05` edges** (`t4_ext`, `early_up_collapse_dn`, `t6_early`, `t4_late`) and compares fire-selection rules: FIFO, highest-EV, highest-WR, cheapest, most-expensive. |
| `sim_methodology.py` | Searches for the **fastest $9→$100 at 0% wipe**: strategy pools (EV>0 / >$0.05 / >$0.10 / large-sample) × selectors × sizing (fixed / adaptive / kelly-lite) × low-tier cap. |

All simulators are deterministic (seeded `random`) and print summary tables to stdout — no files are written.

## Requirements

- **Python 3.8+**, standard library only (`re`, `glob`, `random`, `statistics`, `collections`). No pip install, no virtualenv needed.
- **No wallet / private key / network access.** These are pure offline backtests; they never touch a CLOB client, web3, or real funds.
- Read access to the race-replay log corpus (see **Data**).

## Usage

Run any simulator directly; each prints its own report.

```bash
python3 sim_cheap_entries.py     # core cheap-entry thesis + methodology p_perm
python3 sim_cheap_v2.py          # fixed-fire sizing sweep + cheap-zone EV ranking
python3 sim_cheap_m1.py          # M1-veto OFF vs ON comparison
python3 sim_fire_selection.py    # fire-selection rule comparison (4 sig. edges)
python3 sim_methodology.py       # fastest $9->$100 at 0% wipe search
```

## Data

Every script loads its market history from race-replay logs matched by the hard-coded glob:

```
/home/polybot/polymarket-bot/data/quant_bots_logs_replay/race_test_btc-updown-5m-*.log
```

These logs are **not** committed (see `.gitignore`); fetch them from the private **`polymarket-data`** repo and either place them at the path above or update `PATH_PATTERN` at the top of each file. Each script samples up to 500 logs (seeded) for speed.

> Private research software. No warranty; trades/handles real funds at your own risk.
