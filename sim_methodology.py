#!/usr/bin/env python3
"""sim_methodology.py — find the FASTEST $9→$100 with 0% wipe.

Methodology constraints:
  - Only positive-EV strategies (cd>15, n>=20)
  - Ruin guard ensures 0% wipe (PAUSE at $7, HALT at $5)
  - Selection method: explored — cheapest entry, highest EV, etc.
  - Cap: explored — 1 vs 2 fires per market at low tier

Reports for each methodology:
  - % reach $100
  - % wipe
  - median markets to $100 (speed)
  - p10/p50/p90 final bal
"""
import re
import glob
import random
from collections import defaultdict


PATH_PATTERN = '/home/polybot/polymarket-bot/data/quant_bots_logs_replay/race_test_btc-updown-5m-*.log'
MIN_CD = 15


def load_data():
    """Returns markets dict + strategy EV table."""
    pattern = re.compile(
        r'(\d+)\.\s+(\S+)\s+(?:🔵 SHADOW|🟢 LIVE)\s+(UP|DN)\s+@\s+\$(\d+\.\d+)\s+[\d.]+sh\s+cd=(\d+)')
    winner_pattern = re.compile(r'MARKET RECAP.*\(winner=(\w+)\)')

    paths = sorted(set(glob.glob(PATH_PATTERN)))
    random.seed(42)
    if len(paths) > 500:
        paths = random.sample(paths, 500)

    markets = {}
    all_fires = []
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
            all_fires.append((strat, price, won))
        if fires:
            markets[slug] = {'winner': winner, 'fires': fires}

    # Build EV table
    by_strat = defaultdict(list)
    for strat, price, won in all_fires:
        by_strat[strat].append((price, won))
    ev_table = {}
    for strat, items in by_strat.items():
        if len(items) < 20:
            continue
        ev = sum((1/p - 1) if w else -1.0 for p, w in items) / len(items)
        ev_table[strat] = (ev, len(items))
    return markets, ev_table


def get_cap(bal, low_tier_cap_above_7=1):
    if bal < 5: return 0
    if bal < 7: return 0     # PAUSE — never fire below $7 (prevents wipe)
    if bal < 10: return low_tier_cap_above_7
    if bal < 20: return 2
    if bal < 50: return 3
    return 4


def get_fire_size(bal, sizing_mode='fixed'):
    """Sizing modes:
       'fixed': always $1
       'adaptive': $0.50 below $15, $1 above (protect early bal)
       'kelly_lite': fire size = max(0.25, bal * 0.05) — 5% of bal, min $0.25
    """
    if sizing_mode == 'adaptive':
        return 0.50 if bal < 15 else 1.00
    if sizing_mode == 'kelly_lite':
        return max(0.25, bal * 0.05)
    return 1.00


def select_first(fires, n):
    return fires[:n]


def select_cheapest(fires, n):
    return sorted(fires, key=lambda f: f['price'])[:n]


def select_by_ev(fires, n, ev_table):
    """Highest known-EV strategy first, ties broken by cheapest entry."""
    def key(f):
        ev = ev_table.get(f['strategy'], (-99,))[0]
        return (-ev, f['price'])
    return sorted(fires, key=key)[:n]


def select_cheapest_then_ev(fires, n, ev_table):
    """Cheapest entry first, ties broken by EV."""
    def key(f):
        ev = ev_table.get(f['strategy'], (-99,))[0]
        return (f['price'], -ev)
    return sorted(fires, key=key)[:n]


def simulate(markets_data, slugs_seq, allowed, selector, ev_table,
             low_tier_cap=1, max_mkts=2000, sizing='fixed'):
    bal = 9.0
    peak = 9.0
    max_dd = 0.0
    fires_taken = 0
    wins = 0
    mkts_run = 0
    mkts_to_100 = None

    for slug in slugs_seq[:max_mkts]:
        mkts_run += 1
        m = markets_data[slug]
        cap = get_cap(bal, low_tier_cap)
        if cap == 0:
            continue
        eligible = [f for f in m['fires'] if f['strategy'] in allowed]
        if not eligible:
            continue
        if selector == 'first':
            taken = select_first(eligible, cap)
        elif selector == 'cheapest':
            taken = select_cheapest(eligible, cap)
        elif selector == 'by_ev':
            taken = select_by_ev(eligible, cap, ev_table)
        elif selector == 'cheap_then_ev':
            taken = select_cheapest_then_ev(eligible, cap, ev_table)
        for f in taken:
            fires_taken += 1
            size = get_fire_size(bal, sizing)
            # Don't fire if size would push us below $5 on loss
            if bal - size < 5:
                continue
            if f['won']:
                wins += 1
                bal += size * (1.0 / f['price'] - 1)
            else:
                bal -= size
            if bal > peak: peak = bal
            dd = peak - bal
            if dd > max_dd: max_dd = dd
            if bal >= 100 and mkts_to_100 is None:
                mkts_to_100 = mkts_run
                return {'success': True, 'wiped': False, 'bal': bal,
                        'fires': fires_taken, 'wins': wins, 'max_dd': max_dd,
                        'mkts': mkts_run, 'mkts_to_100': mkts_to_100}
            if bal < 5:
                return {'success': False, 'wiped': True, 'bal': bal,
                        'fires': fires_taken, 'wins': wins, 'max_dd': max_dd,
                        'mkts': mkts_run, 'mkts_to_100': None}
    return {'success': bal >= 100, 'wiped': bal < 5, 'bal': bal,
            'fires': fires_taken, 'wins': wins, 'max_dd': max_dd,
            'mkts': mkts_run, 'mkts_to_100': mkts_to_100}


def run_methodology(markets_data, allowed, selector, ev_table, low_tier_cap=1,
                    n_runs=1000, mkt_budget=2000, sizing='fixed'):
    all_slugs = list(markets_data.keys())
    results = []
    for _ in range(n_runs):
        seq = [random.choice(all_slugs) for _ in range(mkt_budget)]
        r = simulate(markets_data, seq, allowed, selector, ev_table,
                     low_tier_cap, mkt_budget, sizing)
        results.append(r)
    return results


def summarize(name, results):
    n = len(results)
    succ = sum(1 for r in results if r['success'])
    wipe = sum(1 for r in results if r['wiped'])
    bals = sorted([r['bal'] for r in results])
    dds = sorted([r['max_dd'] for r in results])
    succ_mkts = sorted([r['mkts_to_100'] for r in results if r['mkts_to_100']])
    print(f"\n{'='*78}")
    print(f"{name}")
    print(f"{'='*78}")
    print(f"  reach $100: {succ:4d} ({100*succ/n:.1f}%)  wipe: {wipe:4d} ({100*wipe/n:.1f}%)")
    print(f"  final bal p10/50/90/max: ${bals[n//10]:.2f} / ${bals[n//2]:.2f} / ${bals[9*n//10]:.2f} / ${bals[-1]:.2f}")
    print(f"  max DD p50/p90:          ${dds[n//2]:.2f} / ${dds[9*n//10]:.2f}")
    if succ_mkts:
        m_med = succ_mkts[len(succ_mkts)//2]
        m_p25 = succ_mkts[len(succ_mkts)//4]
        m_p75 = succ_mkts[3*len(succ_mkts)//4]
        days_med = m_med / 23
        print(f"  mkts to $100 (success runs): p25={m_p25} med={m_med} p75={m_p75} → ~{days_med:.0f} days @ 23 mkts/day")


def main():
    print("Loading data...")
    markets, ev_table = load_data()
    print(f"  {len(markets)} markets, {len(ev_table)} strategies with n>=20 fires")

    # Define strategy pools
    POSITIVE_EV = {s for s, (ev, n) in ev_table.items() if ev > 0}
    PROFIT_GT_01 = {s for s, (ev, n) in ev_table.items() if ev > 0.10}
    PROFIT_GT_05 = {s for s, (ev, n) in ev_table.items() if ev > 0.05}
    LARGE_SAMPLE_POS = {s for s, (ev, n) in ev_table.items() if ev > 0 and n >= 100}

    print(f"\n  Strategy pools:")
    print(f"    All positive EV (n>=20): {len(POSITIVE_EV)}")
    print(f"    Positive EV with n>=100: {len(LARGE_SAMPLE_POS)}")
    print(f"    EV > $0.05/fire:         {len(PROFIT_GT_05)}")
    print(f"    EV > $0.10/fire:         {len(PROFIT_GT_01)}")

    N_RUNS = 1000
    BUDGET = 2000

    random.seed(42)

    # Methodology = (name, allowed, selector, low_tier_cap, sizing)
    methodologies = [
        ('M_baseline: EV>$0.10 + cheapest + cap=2 + fixed $1',
         PROFIT_GT_01, 'cheapest', 2, 'fixed'),
        ('M_adapt: EV>$0.10 + cheapest + cap=2 + ADAPTIVE size ($0.50 <$15)',
         PROFIT_GT_01, 'cheapest', 2, 'adaptive'),
        ('M_kelly: EV>$0.10 + cheapest + cap=2 + KELLY-LITE (5% of bal)',
         PROFIT_GT_01, 'cheapest', 2, 'kelly_lite'),
        ('M_adapt_cap3: + cap=3 below $10',
         PROFIT_GT_01, 'cheapest', 3, 'adaptive'),
        ('M_kelly_cap3: kelly + cap=3 below $10',
         PROFIT_GT_01, 'cheapest', 3, 'kelly_lite'),
        ('M_kelly_all_pos: KELLY on ALL pos-EV strats + cheapest + cap=3',
         POSITIVE_EV, 'cheapest', 3, 'kelly_lite'),
        ('M_kelly_large: KELLY on n>=100 pos-EV + cheapest + cap=3',
         LARGE_SAMPLE_POS, 'cheapest', 3, 'kelly_lite'),
    ]

    for name, allowed, selector, cap, sizing in methodologies:
        results = run_methodology(markets, allowed, selector, ev_table,
                                  low_tier_cap=cap, n_runs=N_RUNS,
                                  mkt_budget=BUDGET, sizing=sizing)
        summarize(name, results)


if __name__ == "__main__":
    main()
