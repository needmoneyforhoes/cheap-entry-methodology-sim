#!/usr/bin/env python3
"""sim_fire_selection.py — explore fire-selection methods.

Uses the 4 statistically-significant strategies (p_perm < 0.05):
  t4_ext, early_up_collapse_dn, t6_early, t4_late

Tests selection methods:
  A: FIFO (current)
  B: Highest-EV strategy first
  C: Most expensive entry first (favor high-WR signals)
  D: Cheapest entry first (favor high-payoff signals)
  E: Bayesian: only fire if available + market regime matches
"""
import re
import glob
import random
import statistics
from collections import defaultdict


PATH_PATTERN = './data/quant_bots_logs_replay/race_test_btc-updown-5m-*.log'
MIN_CD = 15

# 4 statistically-significant strategies (p_perm < 0.05) with known EV
REAL_EDGE = {
    't4_ext':                (+0.139, 78.2, 'UP-favoring'),
    'early_up_collapse_dn':  (+0.080, 78.2, 'DN-favoring'),
    't6_early':              (+0.074, 90.6, 'UP-favoring'),
    't4_late':               (+0.047, 71.9, 'UP-favoring'),
}


def load_markets():
    pattern = re.compile(
        r'(\d+)\.\s+(\S+)\s+(?:🔵 SHADOW|🟢 LIVE)\s+(UP|DN)\s+@\s+\$(\d+\.\d+)\s+[\d.]+sh\s+cd=(\d+)')
    winner_pattern = re.compile(r'MARKET RECAP.*\(winner=(\w+)\)')

    paths = sorted(set(glob.glob(PATH_PATTERN)))
    random.seed(42)
    if len(paths) > 500:
        paths = random.sample(paths, 500)

    markets = {}
    for p in paths:
        try:
            text = open(p).read()
        except Exception:
            continue
        m = winner_pattern.search(text)
        if not m: continue
        winner = m.group(1)
        if winner not in ('UP', 'DN'): continue
        slug = p.split('-')[-1].replace('.log', '')

        fires = []
        for fm in pattern.finditer(text):
            try:
                strat = fm.group(2)
                side = fm.group(3)
                price = float(fm.group(4))
                cd = int(fm.group(5))
            except Exception:
                continue
            if price <= 0 or price >= 1 or cd <= MIN_CD:
                continue
            won = (side == winner)
            fires.append({'strategy': strat, 'side': side, 'price': price,
                          'cd': cd, 'won': won})
        if fires:
            markets[slug] = {'winner': winner, 'fires': fires}
    return markets


def select_first(fires_filtered, n):
    """Take first chronological N fires."""
    return fires_filtered[:n]


def select_by_known_ev(fires_filtered, n):
    """Take fires sorted by their strategy's known EV (highest first)."""
    sorted_f = sorted(fires_filtered,
                      key=lambda f: -REAL_EDGE.get(f['strategy'], (0,))[0])
    return sorted_f[:n]


def select_high_wr(fires_filtered, n):
    """Take fires sorted by strategy's WR (highest first) — favor confident signals."""
    sorted_f = sorted(fires_filtered,
                      key=lambda f: -REAL_EDGE.get(f['strategy'], (0,0))[1])
    return sorted_f[:n]


def select_cheapest(fires_filtered, n):
    """Take cheapest-entry fires (biggest potential payout)."""
    sorted_f = sorted(fires_filtered, key=lambda f: f['price'])
    return sorted_f[:n]


def select_most_expensive(fires_filtered, n):
    """Take most-expensive entry (most confident signal, but smaller payoff)."""
    sorted_f = sorted(fires_filtered, key=lambda f: -f['price'])
    return sorted_f[:n]


SELECTORS = {
    'A: FIFO (current)': select_first,
    'B: Highest known-EV': select_by_known_ev,
    'C: Highest known-WR': select_high_wr,
    'D: Cheapest entry': select_cheapest,
    'E: Most expensive entry': select_most_expensive,
}


def get_cap(bal):
    """Current ruin guard."""
    if bal < 5: return 0
    if bal < 7: return 0
    if bal < 10: return 1
    if bal < 20: return 2
    if bal < 50: return 3
    return 4


def simulate(markets_data, slugs_seq, selector_fn, max_mkts):
    allowed = set(REAL_EDGE.keys())
    bal = 9.0
    peak = 9.0
    max_dd = 0.0
    fires_taken = 0
    wins = 0

    for slug in slugs_seq[:max_mkts]:
        m = markets_data[slug]
        cap = get_cap(bal)
        if cap == 0:
            continue
        eligible = [f for f in m['fires'] if f['strategy'] in allowed]
        if not eligible:
            continue
        taken = selector_fn(eligible, cap)
        for f in taken:
            fires_taken += 1
            if f['won']:
                wins += 1
                bal += (1.0 / f['price'] - 1)
            else:
                bal -= 1.0
            if bal > peak: peak = bal
            dd = peak - bal
            if dd > max_dd: max_dd = dd
            if bal >= 100:
                return {'success': True, 'wiped': False, 'bal': bal,
                        'fires': fires_taken, 'wins': wins, 'max_dd': max_dd}
            if bal < 5:
                return {'success': False, 'wiped': True, 'bal': bal,
                        'fires': fires_taken, 'wins': wins, 'max_dd': max_dd}

    return {'success': bal >= 100, 'wiped': bal < 5, 'bal': bal,
            'fires': fires_taken, 'wins': wins, 'max_dd': max_dd}


def run_selector(markets_data, selector_fn, n_runs=1000, mkt_budget=1000):
    all_slugs = list(markets_data.keys())
    results = []
    for _ in range(n_runs):
        seq = [random.choice(all_slugs) for _ in range(mkt_budget)]
        results.append(simulate(markets_data, seq, selector_fn, mkt_budget))
    return results


def summarize(name, results, n_runs):
    succ = sum(1 for r in results if r['success'])
    wipe = sum(1 for r in results if r['wiped'])
    bals = sorted([r['bal'] for r in results])
    fires_avg = sum(r['fires'] for r in results) / len(results)
    print(f"\n{'='*70}")
    print(f"{name}")
    print(f"{'='*70}")
    print(f"  reach $100:    {succ:4d}/{n_runs} ({100*succ/n_runs:.1f}%)")
    print(f"  wipe to $5:    {wipe:4d}/{n_runs} ({100*wipe/n_runs:.1f}%)")
    print(f"  bal p10/50/90/max: ${bals[n_runs//10]:.2f} / ${bals[n_runs//2]:.2f} / ${bals[9*n_runs//10]:.2f} / ${bals[-1]:.2f}")
    print(f"  avg fires/run: {fires_avg:.1f}")


def main():
    print("Loading markets...")
    markets = load_markets()
    print(f"  {len(markets)} markets")

    # Coverage check
    eligible_mkts = 0
    total_eligible_fires = 0
    allowed = set(REAL_EDGE.keys())
    for m in markets.values():
        eligible = [f for f in m['fires'] if f['strategy'] in allowed]
        if eligible:
            eligible_mkts += 1
            total_eligible_fires += len(eligible)
    print(f"  {eligible_mkts}/{len(markets)} markets have at least 1 REAL_EDGE fire ({100*eligible_mkts//len(markets)}%)")
    print(f"  {total_eligible_fires} total REAL_EDGE fires (avg {total_eligible_fires/eligible_mkts:.2f}/elig-mkt)")

    N_RUNS = 1000
    MKT_BUDGET = 2000  # bigger budget to allow growth
    random.seed(42)
    print(f"\nMonte Carlo: {N_RUNS} runs × {MKT_BUDGET} markets each")
    print(f"Using ONLY 4 statistically-significant strategies (p_perm < 0.05)")

    for name, sel in SELECTORS.items():
        results = run_selector(markets, sel, n_runs=N_RUNS, mkt_budget=MKT_BUDGET)
        summarize(name, results, N_RUNS)


if __name__ == "__main__":
    main()
