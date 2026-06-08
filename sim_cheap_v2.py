#!/usr/bin/env python3
"""sim_cheap_v2.py — cheap-entry methodology, fixed fire size, proper p_perm.

User constraints:
  - Entries ≤ $0.50 only (cheap-side asymmetric payoff)
  - Profitable strategies (positive EV, no per-strat p_perm required)
  - Fixed fire size (NOT Kelly)
  - Methodology p_perm should be < 1 (beats some random)

To allow recovery from low bal without wipe:
  - Use small fixed fire size + PAUSE just above (fire + halt) so 1 loss can't wipe
  - e.g., fire $0.25, halt $5.00, PAUSE $5.25 → loss takes us to $5.00 exactly
"""
import re
import glob
import random
from collections import defaultdict


PATH_PATTERN = './data/quant_bots_logs_replay/race_test_btc-updown-5m-*.log'
MIN_CD = 15
HALT_THRESH = 5.00


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


def compute_strategy_ev(markets, max_entry=1.0):
    by_strat = defaultdict(list)
    for m in markets.values():
        for f in m['fires']:
            if f['price'] <= max_entry:
                by_strat[f['strategy']].append((f['price'], f['won']))
    ev_table = {}
    for s, items in by_strat.items():
        if len(items) < 10: continue
        ev = sum((1/p - 1) if w else -1.0 for p, w in items) / len(items)
        ev_table[s] = (ev, len(items))
    return ev_table


def simulate(markets_data, slugs_seq, allowed, max_entry, fire_size,
             pause_thresh, max_mkts=3000, low_tier_cap=1):
    bal = 9.0
    peak = 9.0
    fires_taken = 0
    wins = 0
    mkts_run = 0
    mkts_to_100 = None

    def get_cap(b):
        if b < pause_thresh: return 0
        if b < 10: return low_tier_cap
        if b < 20: return 2
        if b < 50: return 3
        return 4

    for slug in slugs_seq[:max_mkts]:
        mkts_run += 1
        m = markets_data[slug]
        cap = get_cap(bal)
        if cap == 0: continue
        eligible = sorted([f for f in m['fires']
                           if f['strategy'] in allowed and f['price'] <= max_entry],
                          key=lambda f: f['price'])
        if not eligible: continue
        taken = eligible[:cap]
        for f in taken:
            # Safety check: don't fire if loss would push below HALT
            if bal - fire_size < HALT_THRESH:
                continue
            fires_taken += 1
            if f['won']:
                wins += 1
                bal += fire_size * (1.0 / f['price'] - 1)
            else:
                bal -= fire_size
            if bal > peak: peak = bal
            if bal >= 100 and mkts_to_100 is None:
                return {'success': True, 'wiped': False, 'bal': bal,
                        'fires': fires_taken, 'wins': wins,
                        'mkts_to_100': mkts_run, 'mkts': mkts_run}
            if bal < HALT_THRESH:
                return {'success': False, 'wiped': True, 'bal': bal,
                        'fires': fires_taken, 'wins': wins,
                        'mkts_to_100': None, 'mkts': mkts_run}
    return {'success': bal >= 100, 'wiped': bal < HALT_THRESH, 'bal': bal,
            'fires': fires_taken, 'wins': wins,
            'mkts_to_100': mkts_to_100, 'mkts': mkts_run}


def methodology_p_perm(markets_data, allowed, max_entry, fire_size, pause_thresh,
                       mkt_budget=400, n_perm=500):
    """Run methodology over a fixed market sequence. Compute observed PnL.
    Then permute market winners and recompute PnL with the SAME methodology.
    p_perm = fraction of perms where permuted PnL >= observed PnL.
    """
    slugs = sorted(markets_data.keys())
    random.seed(43)
    random.shuffle(slugs)
    slugs = slugs[:mkt_budget]

    # Build markets snapshot
    def simulate_with_winners(winners_map):
        bal = 9.0
        n_fires = 0
        wins = 0
        for slug in slugs:
            m = markets_data[slug]
            if bal < pause_thresh: continue
            cap = 1 if bal < 10 else (2 if bal < 20 else (3 if bal < 50 else 4))
            eligible = sorted([f for f in m['fires']
                               if f['strategy'] in allowed and f['price'] <= max_entry],
                              key=lambda f: f['price'])[:cap]
            for f in eligible:
                if bal - fire_size < HALT_THRESH:
                    continue
                won = (f['side'] == winners_map[slug])
                n_fires += 1
                if won:
                    bal += fire_size * (1.0/f['price'] - 1)
                    wins += 1
                else:
                    bal -= fire_size
                if bal < HALT_THRESH: break
            if bal < HALT_THRESH: break
        return bal - 9.0, n_fires, wins

    # Observed
    observed_pnl, n_fires_obs, wins_obs = simulate_with_winners(
        {s: markets_data[s]['winner'] for s in markets_data})

    # Permutations
    original_w = [markets_data[s]['winner'] for s in slugs]
    extreme = 0
    for _ in range(n_perm):
        perm = list(original_w)
        random.shuffle(perm)
        perm_w = dict(zip(slugs, perm))
        # Need winners for all markets, even non-in-slugs (use original)
        all_w = {s: markets_data[s]['winner'] for s in markets_data}
        all_w.update(perm_w)
        pp, _, _ = simulate_with_winners(all_w)
        if pp >= observed_pnl:
            extreme += 1
    return observed_pnl, extreme / n_perm, n_fires_obs, wins_obs


def run_mc(markets, allowed, max_entry, fire_size, pause_thresh, n_runs=2000, budget=3000, cap=1):
    slugs = list(markets.keys())
    results = []
    for _ in range(n_runs):
        seq = [random.choice(slugs) for _ in range(budget)]
        results.append(simulate(markets, seq, allowed, max_entry, fire_size,
                                pause_thresh, budget, cap))
    return results


def summarize(name, results):
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

    # Compute EV for ≤$0.50 strategies
    ev_50 = compute_strategy_ev(markets, max_entry=0.50)
    POS_EV_50 = {s for s, (ev, n) in ev_50.items() if ev > 0 and n >= 20}
    print(f"  {len(POS_EV_50)} strategies with positive EV among entries ≤$0.50 (n>=20)")
    print("  Top strategies (by EV in cheap-entry zone):")
    for s, (ev, n) in sorted(ev_50.items(), key=lambda x: -x[1][0])[:10]:
        if ev > 0:
            print(f"    {s:<35} n={n:4d}  EV/$1 fire=${ev:+.3f}")

    random.seed(42)

    print(f"\n{'='*78}")
    print("METHODOLOGY p_perm (deterministic single-pass over 400 markets)")
    print(f"{'='*78}")
    # Try a few combos
    combos = [
        ("entry≤$0.50, fixed $0.50, PAUSE $5.50", POS_EV_50, 0.50, 0.50, 5.50),
        ("entry≤$0.30, fixed $0.50, PAUSE $5.50", POS_EV_50, 0.30, 0.50, 5.50),
        ("entry≤$0.50, fixed $0.25, PAUSE $5.25", POS_EV_50, 0.50, 0.25, 5.25),
        ("entry≤$0.30, fixed $0.25, PAUSE $5.25", POS_EV_50, 0.30, 0.25, 5.25),
        ("entry≤$0.50, fixed $1.00, PAUSE $6.00", POS_EV_50, 0.50, 1.00, 6.00),
    ]
    for name, allowed, max_e, fs, pt in combos:
        obs, p, n_f, wins = methodology_p_perm(markets, allowed, max_e, fs, pt,
                                                mkt_budget=400, n_perm=500)
        wr = wins/n_f if n_f else 0
        print(f"\n  {name}:")
        print(f"    fires: {n_f}  wins: {wins} (WR {wr:.1%})  observed PnL: ${obs:+.2f}")
        print(f"    methodology p_perm: {p:.4f}    (<1 = beats random; <0.05 = significant)")

    print(f"\n{'='*78}")
    print("MONTE CARLO — bootstrap 2000 runs of 3000 mkts each")
    print(f"{'='*78}")
    mc_combos = [
        ("entry≤$0.50, fixed $0.50, PAUSE $5.50, cap=1", POS_EV_50, 0.50, 0.50, 5.50, 1),
        ("entry≤$0.30, fixed $0.50, PAUSE $5.50, cap=1", POS_EV_50, 0.30, 0.50, 5.50, 1),
        ("entry≤$0.50, fixed $0.25, PAUSE $5.25, cap=1", POS_EV_50, 0.50, 0.25, 5.25, 1),
        ("entry≤$0.50, fixed $0.25, PAUSE $5.25, cap=2", POS_EV_50, 0.50, 0.25, 5.25, 2),
        ("entry≤$0.50, fixed $0.50, PAUSE $5.50, cap=2", POS_EV_50, 0.50, 0.50, 5.50, 2),
    ]
    for name, allowed, max_e, fs, pt, cap in mc_combos:
        r = run_mc(markets, allowed, max_e, fs, pt, n_runs=2000, budget=3000, cap=cap)
        summarize(name, r)


if __name__ == "__main__":
    main()
