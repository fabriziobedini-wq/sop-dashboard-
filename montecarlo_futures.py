#!/usr/bin/env python3
"""Monte Carlo e replay storico dei due segnali futures validati (cascata di liquidazioni, folla estrema).
Domanda: con quanto rischio per operazione si sopravvive alle serie negative, e quanto può scendere il capitale?
Regola testata: entrata all'apertura della candela 4h dopo il segnale, uscita dopo 72 ore, nessuno stop.
Unità di rischio R = k volte l'ATR(4h) all'entrata, dove k è il 95° percentile della peggior escursione contraria
(in ATR) osservata nei 3 giorni: dimensionando così, una perdita di 1R copre 19 operazioni su 20.
Dati: archivio Binance Futures 01/11/2024 → 31/10/2026, 10 crypto (stesso del backtest)."""
import json, math, os, random
from datetime import datetime, timezone
import backtest_derivati as bd

H = 18
NAMES = {'liquidazioni': 'Liquidazioni (sostituto), contrarian', 'folla estrema': 'Long/short folla estremo, contrarian'}


def events():
    out = {k: [] for k in NAMES}
    for a in bd.ASSETS:
        B = bd.build(a)
        if not B:
            continue
        F = bd.features(B)
        for key, sig in NAMES.items():
            busy = -1
            for f in F:
                i = f['i']
                if i + 1 + H >= len(B) or i <= busy or i < 1:
                    continue
                try:
                    d = bd.SIGNALS[sig](f, B[i], B)
                except Exception:
                    d = None
                if not d:
                    continue
                e = B[i + 1]['o']; x = B[i + H]['c']; atr = B[i]['atr']
                ret = d * (x / e - 1) * 100 - bd.COST
                path = B[i + 1:i + 1 + H]
                mae = max(0.0, max((e - b['l']) if d > 0 else (b['h'] - e) for b in path)) / atr
                out[key].append({'t': B[i + 1]['t'], 'end': B[i + H]['t'] + bd.H4, 'asset': a, 'dir': d, 'ret': ret, 'atr_pct': atr / e * 100, 'mae_atr': mae})
                busy = i + H
    return out


def pct(x, q):
    s = sorted(x); return s[min(len(s) - 1, int(q * (len(s) - 1)))]


def max_dd(curve):
    peak, dd = curve[0], 0
    for v in curve:
        peak = max(peak, v); dd = max(dd, 1 - v / peak)
    return dd * 100


def replay(ev, risk):
    """Replay storico in ordine di tempo: ogni operazione rischia `risk` (frazione del capitale) per 1R."""
    eq = 1.0; curve = [eq]
    for e in sorted(ev, key=lambda z: z['end']):
        eq *= 1 + risk * e['R']
        curve.append(eq)
    return (eq - 1) * 100, max_dd(curve)


def streak(rs):
    best = cur = 0
    for r in rs:
        cur = cur + 1 if r <= 0 else 0; best = max(best, cur)
    return best


def mc(ev, risk, n=100, runs=5000, seed=7):
    rnd = random.Random(seed); R = [e['R'] for e in ev]
    dds, finals, streaks = [], [], []
    for _ in range(runs):
        seq = [rnd.choice(R) for _ in range(n)]
        eq = 1.0; curve = [1.0]
        for r in seq:
            eq *= 1 + risk * r; curve.append(eq)
        dds.append(max_dd(curve)); finals.append((eq - 1) * 100); streaks.append(streak(seq))
    return {'dd_mediano': round(pct(dds, .5), 1), 'dd_95': round(pct(dds, .95), 1), 'dd_99': round(pct(dds, .99), 1),
            'risultato_mediano': round(pct(finals, .5), 1), 'prob_perdita': round(sum(1 for f in finals if f < 0) / runs * 100, 1),
            'serie_negativa_95': pct(streaks, .95)}


def main():
    os.makedirs(bd.CACHE, exist_ok=True)
    EV = events()
    res = {}
    L = [f'# Monte Carlo e replay dei segnali futures ({datetime.now(timezone.utc):%Y-%m-%d %H:%M} UTC)', '',
         'Regola: entrata alla candela 4h dopo il segnale, uscita dopo 72 ore, nessuno stop. 1R = k × ATR(4h) all\'entrata, con k = 95° percentile della peggior escursione contraria. Monte Carlo: 5.000 sequenze di 100 operazioni pescate a caso dalla storia. Replay: le operazioni reali in ordine di tempo, sovrapposte come sono avvenute.', '']
    for key, ev in EV.items():
        if len(ev) < 20:
            continue
        k = pct([e['mae_atr'] for e in ev], .95)
        for e in ev:
            e['R'] = e['ret'] / (k * e['atr_pct'])
        Rs = [e['R'] for e in ev]
        avgR = sum(Rs) / len(Rs)
        per_year = len(ev) / 2
        r = {'operazioni': len(ev), 'per_anno': round(per_year), 'k_atr': round(k, 2), 'media_pct': round(sum(e['ret'] for e in ev) / len(ev), 2),
             'media_R': round(avgR, 3), 'vinte': round(sum(1 for x in Rs if x > 0) / len(Rs) * 100), 'peggiore_R': round(min(Rs), 2), 'migliore_R': round(max(Rs), 2),
             'escursione_contraria_mediana_atr': round(pct([e['mae_atr'] for e in ev], .5), 2), 'rischio': {}}
        for risk in (0.005, 0.01, 0.02):
            tot, dd = replay(ev, risk)
            r['rischio'][f'{risk*100:g}%'] = {'replay_risultato': round(tot, 1), 'replay_dd': round(dd, 1), **mc(ev, risk)}
        res[key] = r
        L += [f'## {key.capitalize()}', '',
              f"{r['operazioni']} operazioni in 2 anni (circa {r['per_anno']} all'anno), {r['vinte']}% vinte, media {r['media_pct']:+.2f}% = {r['media_R']:+.3f} R. "
              f"1R = {r['k_atr']} ATR (escursione contraria mediana {r['escursione_contraria_mediana_atr']} ATR). Peggiore {r['peggiore_R']} R, migliore {r['migliore_R']} R.", '',
              '| Rischio per operazione (1R) | Replay: risultato 2 anni | Replay: peggior calo | MC 100 operazioni: risultato mediano | MC: calo mediano | MC: calo nel 5% dei casi peggiori | MC: calo nell\'1% peggiore | MC: probabilità di chiudere in perdita | MC: serie di perdite (95%) |',
              '|---|---|---|---|---|---|---|---|---|']
        for rk, v in r['rischio'].items():
            L.append(f"| {rk} | {v['replay_risultato']:+.1f}% | −{v['replay_dd']}% | {v['risultato_mediano']:+.1f}% | −{v['dd_mediano']}% | −{v['dd_95']}% | −{v['dd_99']}% | {v['prob_perdita']}% | {v['serie_negativa_95']} di fila |")
        L.append('')
    L += ['Il Monte Carlo pesca le operazioni come se fossero indipendenti; nella realtà i segnali su più crypto arrivano insieme (stesso movimento di mercato), e il replay storico lo mostra: per questo il budget limita le operazioni aperte nello stesso momento.']
    json.dump(res, open('montecarlo_futures.json', 'w'), indent=1, ensure_ascii=False)
    open('MONTECARLO_FUTURES.md', 'w').write('\n'.join(L) + '\n')
    print('\n'.join(L))


if __name__ == '__main__':
    main()
