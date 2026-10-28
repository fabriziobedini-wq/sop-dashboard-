#!/usr/bin/env python3
"""
Backtest della parte "price action" del SOP (pattern + stop/TP del backend) su storico OKX.
Solo simulazione su dati pubblici: nessun ordine, nessun broker.

Cosa testa: se i pattern (Pin Bar, Engulfing, rimbalzo/rifiuto EMA20/50) usati dal backend
hanno un vantaggio rispetto a entrate casuali con le STESSE regole di stop/TP/pareggio.
Cosa NON testa: il bias da open interest/funding/CVD (storico troppo corto) -> i pattern vengono
valutati in entrambe le direzioni, come se il bias avesse dato long o short.
"""
import json, sys, time, random, statistics
import requests
import sop_monitor_v2 as sop   # riusa detect_pin_bar, detect_engulfing, detect_ema_bounce, calc_atr, calc_sma20

ASSETS = ['BTC', 'ETH', 'BNB', 'XRP', 'SOL', 'TRX', 'HYPE', 'DOGE', 'ZEC']
H4_BARS, H1_BARS = 1500, 6000
BE_TRIGGER, EXPIRE_H = 0.45, 240
H1 = 3600 * 1000
H4 = 4 * H1


def fetch(sym, bar, n):
    out, after = [], None
    while len(out) < n:
        p = {'instId': f'{sym}-USDT-SWAP', 'bar': bar, 'limit': 100}
        if after: p['after'] = after
        try:
            j = requests.get('https://www.okx.com/api/v5/market/history-candles', params=p, timeout=15).json()
        except Exception as e:
            print('errore', sym, bar, e); break
        d = j.get('data') or []
        if not d: break
        out.extend(d); after = d[-1][0]
        time.sleep(0.12)
    out = [r for r in out if r[8] == '1']
    out.sort(key=lambda r: int(r[0]))
    return [{'t': int(r[0]), 'o': float(r[1]), 'h': float(r[2]), 'l': float(r[3]), 'c': float(r[4]), 'v': float(r[6])} for r in out][-n:]


def synthetic(sym, bar, n):
    """Random walk senza vantaggio: serie 1h e 4h COERENTI (la 4h è aggregata dalla 1h)."""
    rnd = random.Random(hash(sym) & 0xffff)
    total1h = H1_BARS + 8
    t0 = 1700000000000 - total1h * H1
    t0 -= t0 % H4
    px, hs = 100.0, []
    for i in range(total1h):
        o = px
        hi = lo = o
        for _ in range(4):
            px *= 1 + rnd.gauss(0, 0.0035)
            hi, lo = max(hi, px), min(lo, px)
        hs.append({'t': t0 + i * H1, 'o': o, 'h': hi, 'l': lo, 'c': px, 'v': rnd.uniform(100, 200)})
    if bar == '1H':
        return hs[-n:]
    h4 = []
    for i in range(0, len(hs) - 3, 4):
        g = hs[i:i + 4]
        h4.append({'t': g[0]['t'], 'o': g[0]['o'], 'h': max(x['h'] for x in g), 'l': min(x['l'] for x in g), 'c': g[-1]['c'], 'v': sum(x['v'] for x in g)})
    return h4[-n:]


def levels(price, atr, d, mult):
    dist = max(atr * mult, price * 0.015)
    if d == 'long':
        return price - dist, price + dist * 2.5, price + dist * 4.0
    return price + dist, price - dist * 2.5, price - dist * 4.0


def simulate(d, entry, stop, tp1, tp2, bars1h, start_t):
    """Stesse regole del registro: pareggio al 45% verso TP1, TP1 -> pareggio, TP2 chiude, stop-first, scadenza 240h."""
    long = d == 'long'
    tp1hit = be = False
    last = None
    for b in bars1h:
        if b['t'] < start_t: continue
        last = b
        if (b['l'] <= stop) if long else (b['h'] >= stop):
            return ('breakeven' if be else 'stop'), (0.0 if be else (stop - entry) / entry * (1 if long else -1) * 100), tp1hit, b['t']
        if (b['h'] >= tp2) if long else (b['l'] <= tp2):
            return 'tp2', abs(tp2 - entry) / entry * 100, True, b['t']
        if not tp1hit and ((b['h'] >= tp1) if long else (b['l'] <= tp1)):
            tp1hit = True; be = True; stop = entry
        if not be:
            dist = abs(tp1 - entry)
            reached = (b['h'] - entry) if long else (entry - b['l'])
            if dist > 0 and reached / dist >= BE_TRIGGER:
                be = True; stop = entry
        if b['t'] - start_t >= EXPIRE_H * H1:
            pnl = (b['c'] - entry) / entry * 100 * (1 if long else -1)
            return 'expired', pnl, tp1hit, b['t']
    return None


def signals_for(sym, h4, h1, kind, d):
    """Per ogni candela 4h chiusa produce (t_ingresso, prezzo, atr, sma20, pattern) se c'è il segnale richiesto."""
    out = []
    for i in range(60, len(h4) - 1):
        nxt = h4[i + 1]
        window = h4[:i + 1] + [{'o': nxt['o'], 'h': nxt['o'], 'l': nxt['o'], 'c': nxt['o'], 'v': 0.0, 't': nxt['t']}]
        price = nxt['o']
        pat = None
        if kind == 'random':
            pat = {'pattern': 'casuale'}
        else:
            if kind in ('pattern', 'pin'):
                pat = sop.detect_pin_bar(window, d)
            if not pat and kind in ('pattern', 'engulf'):
                pat = sop.detect_engulfing(window, d)
            if not pat and kind in ('pattern', 'ema'):
                pat = sop.detect_ema_bounce(window, d)
        if not pat: continue
        atr = sop.calc_atr(window)
        sma20 = sop.calc_sma20(window)
        out.append((nxt['t'], price, atr, sma20, pat['pattern']))
    return out


def run_config(data, kind, mult, flt):
    res = []
    for sym, (h4, h1) in data.items():
        for d in ('long', 'short'):
            busy_until = 0
            for t, price, atr, sma20, name in signals_for(sym, h4, h1, kind, d):
                if t < busy_until: continue          # come il registro: un solo segnale aperto per asset+direzione
                if flt == 'trend' and sma20 is not None:
                    if (d == 'long' and price < sma20) or (d == 'short' and price > sma20): continue
                if flt == 'short_veto' and d == 'short' and sma20 is not None and price > sma20: continue
                stop, tp1, tp2 = levels(price, atr, d, mult)
                r = simulate(d, price, stop, tp1, tp2, h1, t)
                if r is None: continue
                outcome, pnl, tp1hit, tclose = r
                dist_pct = abs(price - stop) / price * 100
                res.append({'sym': sym, 'dir': d, 't': t, 'out': outcome, 'pnl': pnl, 'R': pnl / dist_pct, 'tp1': tp1hit, 'pat': name})
                busy_until = tclose + H1  # un solo segnale aperto per asset+direzione, come il registro
    return res


def summarize(res):
    n = len(res)
    if not n: return None
    c = lambda k: sum(1 for r in res if r['out'] == k)
    return {'n': n, 'tp1%': round(100 * sum(1 for r in res if r['tp1']) / n, 1), 'tp2%': round(100 * c('tp2') / n, 1),
            'be%': round(100 * c('breakeven') / n, 1), 'stop%': round(100 * c('stop') / n, 1),
            'avg_pnl%': round(statistics.mean(r['pnl'] for r in res), 3), 'avg_R': round(statistics.mean(r['R'] for r in res), 3),
            'tot_pnl%': round(sum(r['pnl'] for r in res), 1)}


def main():
    syn = '--synthetic' in sys.argv
    getter = synthetic if syn else fetch
    data = {}
    for s in ASSETS:
        h4, h1 = getter(s, '4H', H4_BARS), getter(s, '1H', H1_BARS)
        if len(h4) > 120 and len(h1) > 500:
            data[s] = (h4, h1)
        print(f'{s}: {len(h4)} barre 4h, {len(h1)} barre 1h', flush=True)
    rows = []
    for kind in ('random', 'pattern', 'pin', 'engulf', 'ema'):
        for mult in (1.0, 1.5, 2.5):
            for flt in ('none', 'trend'):
                res = run_config(data, kind, mult, flt)
                sm = summarize(res)
                if sm: rows.append({'kind': kind, 'stop_mult_ATR': mult, 'filtro': flt, **sm})
    # stabilità: pattern/1.5/none, prima metà vs seconda metà e ultimi 30 giorni
    base = run_config(data, 'pattern', 1.5, 'none')
    base.sort(key=lambda r: r['t'])
    half = len(base) // 2
    last_t = max(r['t'] for r in base) if base else 0
    stab = {'prima_meta': summarize(base[:half]), 'seconda_meta': summarize(base[half:]),
            'ultimi_30g': summarize([r for r in base if r['t'] >= last_t - 30 * 24 * H1])}
    by_dir = {d: summarize([r for r in base if r['dir'] == d]) for d in ('long', 'short')}
    by_pat = {}
    for r in base: by_pat.setdefault(r['pat'], []).append(r)
    by_pat = {k: summarize(v) for k, v in by_pat.items()}
    span = {s: [time.strftime('%Y-%m-%d', time.gmtime(h4[0]['t'] / 1000)), time.strftime('%Y-%m-%d', time.gmtime(h4[-1]['t'] / 1000))] for s, (h4, h1) in data.items()}
    out = {'sintetico': syn, 'periodo': span, 'righe': rows, 'stabilita': stab, 'per_direzione': by_dir, 'per_pattern': by_pat}
    json.dump(out, open('backtest_results.json', 'w'), indent=1, ensure_ascii=False)

    L = ['# Backtest SOP (price action) — storico OKX' + (' [DATI SINTETICI: solo test del codice]' if syn else ''), '',
         'Regole simulate come il backend: stop = max(1,5×ATR4h; 1,5%), TP1 = 2,5R, TP2 = 4R, pareggio al 45% verso TP1, TP1 → pareggio, scadenza 240h, stop-first nella stessa candela 1h. Entrata all\'apertura della 4h successiva al pattern. Nessuna commissione né slippage. Un solo segnale per asset+direzione alla volta. Pattern valutati in entrambe le direzioni (il bias OI/funding/CVD non è testabile su storico lungo).', '',
         'Periodo per asset: ' + ', '.join(f'{s} {a}→{b}' for s, (a, b) in span.items()), '',
         '| segnali | stop×ATR | filtro | n | TP1% | TP2% | BE% | stop% | media % | media R | tot % |', '|---|---|---|---|---|---|---|---|---|---|---|']
    for r in rows:
        L.append(f"| {r['kind']} | {r['stop_mult_ATR']} | {r['filtro']} | {r['n']} | {r['tp1%']} | {r['tp2%']} | {r['be%']} | {r['stop%']} | {r['avg_pnl%']} | {r['avg_R']} | {r['tot_pnl%']} |")
    L += ['', '## Stabilità (pattern, stop 1,5×ATR, nessun filtro)', '```', json.dumps(stab, indent=1), '```',
          '## Per direzione', '```', json.dumps(by_dir, indent=1), '```', '## Per pattern', '```', json.dumps(by_pat, indent=1), '```']
    open('BACKTEST.md', 'w').write('\n'.join(L) + '\n')
    print('\n'.join(L[:40]))


if __name__ == '__main__':
    main()
