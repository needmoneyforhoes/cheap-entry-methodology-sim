#!/usr/bin/env python3
"""sim_cheap_entries.py — cheap-entry methodology with p_perm validation.

User insight: PERM_SIGNIFICANT strategies all have HIGH entries ($0.69-$0.85).
High entry = small per-win payoff. We were leaving asymmetric payoff on the table.

NEW methodology:
  - Filter to fires with entry price ≤ $0.50 (cheap side = bigger payouts)
  - Use ANY strategy with overall positive EV (no per-strategy p_perm requirement)
  - Fixed fire size $1.00 (NO Kelly)
  - Ruin guard: PAUSE $7 (0% wipe)

Test methodology-level p_perm:
  - Methodology p_perm = fraction of permutations of winners that gave PnL >= observed
  - p_perm < 1 = methodology beats some random orderings
  - p_perm < 0.05 = methodology beats nearly all random orderings (publishable significance)
"""
import re
import glob
import random
from collections import defaultdict


PATH_PATTERN = './data/quant_bots_logs_replay/race_test_btc-updown-5m-*.log'
MIN_CD = 15
FIRE_SIZE = 1.00
PAUSE_THRESH = 7.0
HALT_THRESH = 5.0
N_PERM = 1000


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
        try: text = open(p).read()
        except: continue
        m = winner_pattern.search(text)
        if not m: continue
        winner = m.group(1)
        if winner not in ('UP', 'DN'): continue
        slug = p.split('-')[-1].replace('.log', '')
        fires = []
        for fm in pattern.finditer(text):
            try:
                strat = fm.group(2); side = fm.group(3)
                price = float(fm.group(4)); cd = int(fm.group(5))
            except: continue
            if price <= 0 or price >= 1 or cd <= MIN_CD: continue
            won = (side == winner)
            fires.append({'strategy': strat, 'side': side, 'price': price,
                          'cd': cd, 'won': won})
        if fires:
            markets[slug] = {'winner': winner, 'fires': fires}
    return markets


def compute_strategy_ev(markets):
    """Per-strategy EV (cd>15, all entries)."""
    by_strat = defaultdict(list)
    for m in markets.values():
        for f in m['fires']:
            by_strat[f['strategy']].append((f['price'], f['won']))
    ev_table = {}
    for s, items in by_strat.items():
        if len(items) < 20: continue
        ev = sum((1/p - 1) if w else -1.0 for p, w in items) / len(items)
        ev_table[s] = (ev, len(items))
    return ev_table


def get_cap(bal):
    if bal < HALT_THRESH: return 0
    if bal < PAUSE_THRESH: return 0
    if bal < 10: return 1
    if bal < 20: return 2
    if bal < 50: return 3
    return 4


def select_eligible(fires, allowed_strats, max_entry):
    """Filter fires by strategy and max entry, sorted by cheapest first."""
    elig = [f for f in fires
            if f['strategy'] in allowed_strats and f['price'] <= max_entry]
    return sorted(elig, key=lambda f: f['price'])


def simulate(markets_data, slugs_seq, allowed, max_entry, max_mkts=3000):
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
        cap = get_cap(bal)
        if cap == 0: continue
        eligible = select_eligible(m['fires'], allowed, max_entry)
        if not eligible: continue
        taken = eligible[:cap]
        for f in taken:
            fires_taken += 1
            if f['won']:
                wins += 1
                bal += FIRE_SIZE * (1.0 / f['price'] - 1)
            else:
                bal -= FIRE_SIZE
            if bal > peak: peak = bal
            dd = peak - bal
            if dd > max_dd: max_dd = dd
            if bal >= 100 and mkts_to_100 is None:
                return {'success': True, 'wiped': False, 'bal': bal,
                        'fires': fires_taken, 'wins': wins, 'max_dd': max_dd,
                        'mkts_to_100': mkts_run, 'mkts': mkts_run}
            if bal < HALT_THRESH:
                return {'success': False, 'wiped': True, 'bal': bal,
                        'fires': fires_taken, 'wins': wins, 'max_dd': max_dd,
                        'mkts_to_100': None, 'mkts': mkts_run}
    return {'success': bal >= 100, 'wiped': bal < HALT_THRESH, 'bal': bal,
            'fires': fires_taken, 'wins': wins, 'max_dd': max_dd,
            'mkts_to_100': mkts_to_100, 'mkts': mkts_run}


def methodology_p_perm(markets_data, allowed, max_entry, mkt_budget=500, n_perm=1000):
    """Compute observed total PnL across all markets in order vs permuted.

    Use a fixed deterministic sequence — all markets once — for both observed
    and permuted. Permute the WINNER assignments and recompute PnL.
    Returns (observed_pnl, p_perm).
    """
    slugs = list(markets_data.keys())
    random.seed(43)
    random.shuffle(slugs)
    slugs = slugs[:mkt_budget]

    # Observed PnL
    bal = 9.0
    fires_log = []  # remember fires that WERE taken for permutation
    for slug in slugs:
        m = markets_data[slug]
        cap = get_cap(bal)
        if cap == 0: continue
        eligible = select_eligible(m['fires'], allowed, max_entry)
        if not eligible: continue
        taken = eligible[:cap]
        for f in taken:
            fires_log.append((slug, f['side'], f['price']))
            if f['won']:
                bal += FIRE_SIZE * (1.0/f['price'] - 1)
            else:
                bal -= FIRE_SIZE
            if bal < HALT_THRESH or bal >= 100: break
        if bal < HALT_THRESH or bal >= 100: break
    observed_pnl = bal - 9.0

    # Permutation: shuffle market winners, recompute PnL using SAME fires
    original_winners = {s: markets_data[s]['winner'] for s in markets_data}
    extreme = 0
    winners_pool = list(original_winners.values())
    for _ in range(n_perm):
        random.shuffle(winners_pool)
        perm_w = dict(zip(original_winners.keys(), winners_pool))
        bal2 = 9.0
        for slug, side, price in fires_log:
            won = (side == perm_w.get(slug, original_winners[slug]))
            if won:
                bal2 += FIRE_SIZE * (1.0/price - 1)
            else:
                bal2 -= FIRE_SIZE
            if bal2 < HALT_THRESH: break
        perm_pnl = bal2 - 9.0
        if perm_pnl >= observed_pnl: extreme += 1
    return observed_pnl, extreme / n_perm, len(fires_log)


def run_monte_carlo(markets_data, allowed, max_entry, n_runs=2000, budget=3000):
    all_slugs = list(markets_data.keys())
    results = []
    for _ in range(n_runs):
        seq = [random.choice(all_slugs) for _ in range(budget)]
        results.append(simulate(markets_data, seq, allowed, max_entry, budget))
    return results


def summarize_runs(name, results):
    n = len(results)
    succ = sum(1 for r in results if r['success'])
    wipe = sum(1 for r in results if r['wiped'])
    bals = sorted([r['bal'] for r in results])
    succ_mkts = sorted([r['mkts_to_100'] for r in results if r['mkts_to_100']])
    print(f"\n{name}")
    print(f"  reach $100: {succ:5d}/{n} ({100*succ/n:.1f}%)   wipe: {wipe:5d} ({100*wipe/n:.1f}%)")
    print(f"  bal p10/50/90: ${bals[n//10]:.2f} / ${bals[n//2]:.2f} / ${bals[9*n//10]:.2f}")
    if succ_mkts:
        nm = len(succ_mkts)
        m_med = succ_mkts[nm//2]
        print(f"  mkts to $100: p25={succ_mkts[nm//4]} p50={m_med} p75={succ_mkts[3*nm//4]}")
        print(f"  → $/mkt at p50: ${91/m_med:.3f}")


def main():
    markets = load_markets()
    print(f"Loaded {len(markets)} markets")

    # Compute strategy EVs
    ev_table = compute_strategy_ev(markets)
    POS_EV = {s for s, (ev, n) in ev_table.items() if ev > 0}
    print(f"  {len(POS_EV)} strategies with overall positive EV (n>=20)")

    random.seed(42)

    # Coverage at different entry caps
    for max_e in [0.20, 0.30, 0.40, 0.50]:
        coverage = sum(1 for m in markets.values()
                       if any(f['strategy'] in POS_EV and f['price'] <= max_e
                              for f in m['fires']))
        n_fires = sum(1 for m in markets.values()
                      for f in m['fires']
                      if f['strategy'] in POS_EV and f['price'] <= max_e)
        print(f"  entry≤${max_e:.2f}: {coverage}/{len(markets)} mkts cover ({100*coverage/len(markets):.0f}%), {n_fires} eligible fires")

    print(f"\n{'='*78}")
    print("METHODOLOGY p_perm VALIDATION")
    print(f"{'='*78}")
    for max_e in [0.20, 0.30, 0.40, 0.50]:
        obs_pnl, p_perm, n_fires = methodology_p_perm(
            markets, POS_EV, max_e, mkt_budget=len(markets), n_perm=N_PERM)
        print(f"\n  POS_EV strategies + entry≤${max_e:.2f}:")
        print(f"    fires taken in deterministic run: {n_fires}")
        print(f"    observed PnL: ${obs_pnl:+.2f} (from $9 start)")
        print(f"    p_perm: {p_perm:.4f}    (<1 = beats random; <0.05 = significant)")

    print(f"\n{'='*78}")
    print("MONTE CARLO — speed/safety per entry cap")
    print(f"{'='*78}")
    for max_e in [0.20, 0.30, 0.40, 0.50]:
        r = run_monte_carlo(markets, POS_EV, max_e, n_runs=2000, budget=3000)
        summarize_runs(f"POS_EV + entry≤${max_e:.2f} + fixed $1 + PAUSE $7", r)


if __name__ == "__main__":
    main()
