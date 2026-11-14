#!/usr/bin/env python3
"""Backtest della checklist "fine della discesa": quando una crypto è scesa, quante condizioni
servono per ricomprare con un vantaggio misurabile?

Contesto: si guarda solo quando il prezzo è almeno 10% sotto il massimo delle ultime 20 giornate.
Le 7 condizioni (calcolate alla chiusura di ogni candela da 4 ore, solo con dati già disponibili):
 1 cascata di liquidazioni dei long nelle ultime 72 ore (candela > 2,5 ATR in discesa, OI -2%)
 2 la folla non è più long estrema (long/short dei conti sotto il 70° percentile di 90 giorni)
 3 leva scaricata: open interest almeno 10% sotto il massimo delle ultime 24 candele (4 giorni)
 4 funding negativo
 5 tornano gli acquisti aggressivi: volume aggressivo in acquisto > 51% nelle ultime 24 ore
 6 prezzo sopra la media a 20 candele (4h)
 7 minimo crescente: minimo delle ultime 6 candele sopra il minimo delle 6 precedenti
Entrata all'apertura della candela successiva. Due modi di uscita:
 A) a tempo: dopo 72 ore e dopo 7 giorni
 B) con stop e target: stop sotto il minimo delle ultime 12 candele (-0,5 ATR), target 2 volte il rischio, massimo 7 giorni
Confronto: ricomprare in un momento qualsiasi della stessa discesa (stesse regole di uscita).
Costi 0,1%. Dati: archivio Binance Futures, 01/11/2024 → 31/10/2026, 10 crypto."""
import json, math, os
from datetime import datetime, timezone
import backtest_derivati as bd

H72, H7D, COST = 18, 42, 0.10


def ema(vals, n):
    out, e = [], None
    for v in vals:
        e = v if e is None else v * 2 / (n + 1) + e * (n - 1) / (n + 1)
        out.append(e)
    return out


def conditions(B, F):
    c = [b['c'] for b in B]
    e20 = ema(c, 20)
    rows = []
    last_liq = -999
    for i, (b, f) in enumerate(zip(B, F)):
        if i < 130:
            rows.append(None); continue
        try:
            if bd.SIGNALS['Liquidazioni (sostituto), contrarian'](f, b, B) == 1:
                last_liq = i
        except Exception:
            pass
        hi20d = max(x['c'] for x in B[i - 119:i + 1])
        dd = (b['c'] / hi20d - 1) * 100
        ois = [x['oi'] for x in B[i - 23:i + 1] if x['oi']]
        sl = B[i - 5:i + 1]
        buy = sum(x['tb'] for x in sl) / max(1e-9, sum(x['v'] for x in sl))
        cond = [
            i - last_liq <= 18,
            f.get('ls_all_rk') is not None and f['ls_all_rk'] < 0.70,
            bool(ois) and b['oi'] is not None and b['oi'] <= 0.90 * max(ois),
            f.get('fr') is not None and f['fr'] < 0,
            buy > 0.51,
            b['c'] > e20[i],
            min(x['l'] for x in B[i - 5:i + 1]) > min(x['l'] for x in B[i - 11:i - 5]),
        ]
        rows.append({'dd': dd, 'cond': cond, 'score': sum(cond)})
    return rows


def trade_fixed(B, i, hz):
    if i + 1 + hz >= len(B):
        return None
    return (B[i + hz]['c'] / B[i + 1]['o'] - 1) * 100 - COST


def trade_stop(B, i):
    if i + 1 + H7D >= len(B):
        return None
    e = B[i + 1]['o']
    st = min(x['l'] for x in B[i - 11:i + 1]) - 0.5 * B[i]['atr']
    risk = e - st
    if risk <= 0:
        return None
    tp = e + 2 * risk
    for x in B[i + 1:i + 1 + H7D]:
        if x['l'] <= st:
            return (st / e - 1) * 100 - COST
        if x['h'] >= tp:
            return (tp / e - 1) * 100 - COST
    return (B[i + H7D]['c'] / e - 1) * 100 - COST


def summ(x):
    x = [v for v in x if v is not None]
    n = len(x)
    if n < 2:
        return {'n': n}
    m = sum(x) / n
    sd = math.sqrt(sum((v - m) ** 2 for v in x) / (n - 1))
    return {'n': n, 'media': round(m, 2), 'vinte': round(sum(1 for v in x if v > 0) / n * 100), 't': round(m / sd * math.sqrt(n), 2) if sd else 0}


def run():
    import os
    os.makedirs(bd.CACHE, exist_ok=True)
    series = {}
    for a in bd.ASSETS:
        B = bd.build(a)
        if B:
            series[a] = (B, conditions(B, bd.features(B)))
    mid = datetime(2025, 11, 1, tzinfo=timezone.utc).timestamp() * 1000
    tests = {}

    def collect(name, pick):
        ev = {'72h': [], '7g': [], 'stop/target': [], 'anno1': [], 'anno2': []}
        per_asset = {}
        for a, (B, R) in series.items():
            busy = -1
            for i, r in enumerate(R):
                if r is None or r['dd'] > -10 or i <= busy or not pick(r):
                    continue
                f72, f7, fs = trade_fixed(B, i, H72), trade_fixed(B, i, H7D), trade_stop(B, i)
                if f72 is None:
                    continue
                ev['72h'].append(f72); ev['7g'].append(f7); ev['stop/target'].append(fs)
                (ev['anno1'] if B[i]['t'] < mid else ev['anno2']).append(fs)
                per_asset.setdefault(a, []).append(fs if fs is not None else 0)
                busy = i + H72
        tests[name] = {k: summ(v) for k, v in ev.items()}
        tests[name]['asset_positivi'] = f"{sum(1 for v in per_asset.values() if sum(v) > 0)}/{len(per_asset)}"

    collect('Confronto: ricomprare in un momento qualsiasi della discesa', lambda r: True)
    for k in range(2, 7):
        collect(f'Almeno {k} condizioni su 7', lambda r, k=k: r['score'] >= k)
    names = ['1 cascata liquidazioni long', '2 folla non più long estrema', '3 leva scaricata (OI -10%)', '4 funding negativo',
             '5 tornano gli acquisti aggressivi', '6 prezzo sopra media 20 (4h)', '7 minimo crescente (4h)']
    for j, nm in enumerate(names):
        collect(f'Solo condizione {nm}', lambda r, j=j: r['cond'][j])
    collect('Liquidazioni + folla non più estrema + una conferma di prezzo (6 o 7)',
            lambda r: r['cond'][0] and r['cond'][1] and (r['cond'][5] or r['cond'][6]))
    collect('Leva scaricata + folla non più estrema + una conferma di prezzo (6 o 7)',
            lambda r: r['cond'][2] and r['cond'][1] and (r['cond'][5] or r['cond'][6]))
    return series, tests


def main():
    series, T = run()
    json.dump(T, open('backtest_ripartenza.json', 'w'), indent=1, ensure_ascii=False)
    f = lambda s: '—' if s.get('n', 0) < 2 else f"{s['media']:+.2f}% ({s['vinte']}% vinte, t {s['t']})"
    L = [f'# Backtest "fine della discesa" ({datetime.now(timezone.utc):%Y-%m-%d %H:%M} UTC)', '',
         f'Periodo {bd.START:%d/%m/%Y} → {bd.END:%d/%m/%Y}, candele 4h dei futures Binance su {len(series)} crypto. Solo momenti con prezzo almeno 10% sotto il massimo di 20 giorni. Entrata alla candela successiva, costi 0,1%, operazioni non sovrapposte (72 ore) sullo stesso asset.', '',
         '| Regola di riacquisto | Casi | Uscita a 72 ore | Uscita a 7 giorni | Stop e target 2:1 (max 7 giorni) | 1° anno (stop/target) | 2° anno (stop/target) | Asset positivi |',
         '|---|---|---|---|---|---|---|---|']
    for name, s in T.items():
        L.append(f"| {name} | {s['72h'].get('n', 0)} | {f(s['72h'])} | {f(s['7g'])} | {f(s['stop/target'])} | {f(s['anno1'])} | {f(s['anno2'])} | {s['asset_positivi']} |")
    L += ['', 'Una regola vale qualcosa solo se batte il confronto in entrambi gli anni e su quasi tutti gli asset. La quota di stablecoin (USDT dominance) non è nell\'archivio e non è testata.']
    open('BACKTEST_RIPARTENZA.md', 'w').write('\n'.join(L) + '\n')
    print('\n'.join(L))


if __name__ == '__main__':
    main()
