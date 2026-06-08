#!/usr/bin/env python3
"""sim_cheap_m1.py — cheap-entry methodology WITH M1 veto applied.

User insight: must include ALL bot edge in simulation. M1 catches ~58% of losers
(and falsely blocks ~23% of winners). Apply M1 probabilistically per fire.

M1 calibration (from 535-mkt shadow_predictor state):
  - When side WOULD have LOST (side != winner):
      M1 blocks: 58% chance (true positive)
      M1 allows: 42% (miss)
  - When side WOULD have WON (side == winner):
      M1 blocks: 23% (false positive — costly miss)
      M1 allows: 77%

Net effect: M1 catches more losses than wins → positive expected lift.

Comparison: same methodology with M1 OFF vs M1 ON.
"""
import re
import glob
import random
from collections import defaultdict


PATH_PATTERN = './data/quant_bots_logs_replay/race_test_btc-updown-5m-*.log'
MIN_CD = 15
HALT_THRESH = 5.00

# M1 calibration from shadow_predictors_state.json:
#   blocks_correct: 6677, blocks_incorrect: 2535
#   allows_correct: 8292, allows_incorrect: 4828
# When LOSER: M1 blocks 6677/(6677+4828) = 58.0%
# When WINNER: M1 blocks 2535/(2535+8292) = 23.4%
M1_BLOCK_PROB_WHEN_LOSER = 0.580
M1_BLOCK_PROB_WHEN_WINNER = 0.234


def m1_simulated_verdict(would_win, rng=None):
    """Return True if M1 would have allowed this fire (let it through)."""
    if rng is None:
        rng = random
    if would_win:
        return rng.random() > M1_BLOCK_PROB_WHEN_WINNER
    return rng.random() > M1_BLOCK_PROB_WHEN_LOSER


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
        if len(items) < 20: continue
        ev = sum((1/p - 1) if w else -1.0 for p, w in items) / len(items)
        ev_table[s] = (ev, len(items))
    return ev_table


def simulate(markets_data, slugs_seq, allowed, max_entry, fire_size,
             pause_thresh, max_mkts=3000, low_tier_cap=1, m1_enabled=False, rng=None):
    if rng is None:
        rng = random
    bal = 9.0
    peak = 9.0
    fires_taken = 0
    wins = 0
    m1_blocks = 0
    m1_blocks_correct = 0  # M1 blocked a loser (good)
    m1_blocks_incorrect = 0  # M1 blocked a winner (bad)
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
        # Take fires one at a time, applying M1 veto
        taken_count = 0
        for f in eligible:
            if taken_count >= cap: break
            if m1_enabled:
                allow = m1_simulated_verdict(f['won'], rng)
                if not allow:
                    m1_blocks += 1
                    if not f['won']:
                        m1_blocks_correct += 1
                    else:
                        m1_blocks_incorrect += 1
                    continue  # M1 blocked → skip this fire
            if bal - fire_size < HALT_THRESH:
                continue
            fires_taken += 1
            taken_count += 1
            if f['won']:
                wins += 1
                bal += fire_size * (1.0 / f['price'] - 1)
            else:
                bal -= fire_size
            if bal > peak: peak = bal
            if bal >= 100 and mkts_to_100 is None:
                return {'success': True, 'wiped': False, 'bal': bal,
                        'fires': fires_taken, 'wins': wins,
                        'm1_blocks': m1_blocks,
                        'm1_blocks_correct': m1_blocks_correct,
                        'm1_blocks_incorrect': m1_blocks_incorrect,
                        'mkts_to_100': mkts_run, 'mkts': mkts_run}
            if bal < HALT_THRESH:
                return {'success': False, 'wiped': True, 'bal': bal,
                        'fires': fires_taken, 'wins': wins,
                        'm1_blocks': m1_blocks,
                        'm1_blocks_correct': m1_blocks_correct,
                        'm1_blocks_incorrect': m1_blocks_incorrect,
                        'mkts_to_100': None, 'mkts': mkts_run}
    return {'success': bal >= 100, 'wiped': bal < HALT_THRESH, 'bal': bal,
            'fires': fires_taken, 'wins': wins,
            'm1_blocks': m1_blocks,
            'm1_blocks_correct': m1_blocks_correct,
            'm1_blocks_incorrect': m1_blocks_incorrect,
            'mkts_to_100': mkts_to_100, 'mkts': mkts_run}


def run_mc(markets, allowed, max_entry, fire_size, pause_thresh, cap=1,
           m1_enabled=False, n_runs=2000, budget=3000):
    slugs = list(markets.keys())
    rng = random.Random(42)
    results = []
    for _ in range(n_runs):
        seq = [rng.choice(slugs) for _ in range(budget)]
        results.append(simulate(markets, seq, allowed, max_entry, fire_size,
                                pause_thresh, budget, cap, m1_enabled, rng))
    return results


def summarize(name, results):
    n = len(results)
    succ = sum(1 for r in results if r['success'])
    wipe = sum(1 for r in results if r['wiped'])
    bals = sorted([r['bal'] for r in results])
    succ_mkts = sorted([r['mkts_to_100'] for r in results if r['mkts_to_100']])
    m1_b = sum(r['m1_blocks'] for r in results)
    m1_c = sum(r['m1_blocks_correct'] for r in results)
    m1_i = sum(r['m1_blocks_incorrect'] for r in results)
    print(f"\n{name}")
    print(f"  reach $100: {succ:5d}/{n} ({100*succ/n:.1f}%)   wipe: {wipe:5d} ({100*wipe/n:.1f}%)")
    print(f"  bal p10/50/90: ${bals[n//10]:.2f} / ${bals[n//2]:.2f} / ${bals[9*n//10]:.2f}")
    if succ_mkts:
        nm = len(succ_mkts)
        m_med = succ_mkts[nm//2]
        print(f"  mkts to $100: p25={succ_mkts[nm//4]} p50={m_med} p75={succ_mkts[3*nm//4]}")
        print(f"  → $/mkt at p50: ${91/m_med:.3f}")
    if m1_b > 0:
        print(f"  M1: blocked {m1_b} fires ({100*m1_c/m1_b:.0f}% caught real losers, {100*m1_i/m1_b:.0f}% blocked real winners)")


def main():
    markets = load_markets()
    print(f"Loaded {len(markets)} markets")

    ev_50 = compute_strategy_ev(markets, max_entry=0.50)
    POS_EV_50 = {s for s, (ev, n) in ev_50.items() if ev > 0 and n >= 20}
    print(f"  {len(POS_EV_50)} cheap-side positive-EV strategies")

    random.seed(42)
    print(f"\n{'='*78}")
    print("COMPARE: same methodology, M1 OFF vs M1 ON (simulated)")
    print(f"{'='*78}")

    configs = [
        ('entry≤$0.50, fixed $0.50, PAUSE $5.50, cap=1', POS_EV_50, 0.50, 0.50, 5.50, 1),
        ('entry≤$0.30, fixed $0.50, PAUSE $5.50, cap=1', POS_EV_50, 0.30, 0.50, 5.50, 1),
        ('entry≤$0.50, fixed $0.25, PAUSE $5.25, cap=1', POS_EV_50, 0.50, 0.25, 5.25, 1),
        ('entry≤$0.50, fixed $0.50, PAUSE $5.50, cap=2', POS_EV_50, 0.50, 0.50, 5.50, 2),
    ]
    for name, allowed, me, fs, pt, cap in configs:
        print(f"\n--- {name} ---")
        r_off = run_mc(markets, allowed, me, fs, pt, cap, m1_enabled=False)
        summarize("  M1 OFF", r_off)
        r_on = run_mc(markets, allowed, me, fs, pt, cap, m1_enabled=True)
        summarize("  M1 ON ", r_on)


if __name__ == "__main__":
    main()
