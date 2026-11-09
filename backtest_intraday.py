#!/usr/bin/env python3
"""
Backtest INTRADAY del livello "derivati" del metodo SOP.

Domanda: open interest, funding, CVD vero (volume aggressivo), rapporto
long/short e liquidazioni anticipano il prezzo nelle 1-4-8 ore successive,
su barre da 15 minuti, più del caso e al netto dei costi?
Solo misura statistica: nessun ordine, nessun broker, nessuna chiave API.

Dati: archivio pubblico Binance Futures USDⓈ-M (data.binance.vision)
  - klines 15m (con taker buy volume -> CVD vero)
  - metrics 5 minuti: open interest, long/short top trader e folla, rapporto taker
  - funding rate storico
Uscita: BACKTEST_INTRADAY.md e backtest_intraday.json
"""
import bisect, csv, io, json, math, os, sys, time, zipfile
from collections import deque
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta, timezone
import requests

BASE = 'https://data.binance.vision/data/futures/um'
ASSETS = ['BTC', 'ETH', 'SOL', 'XRP', 'BNB', 'DOGE', 'ADA', 'LINK', 'AVAX', 'TRX']
START = date(2024, 11, 1)
END = date(2026, 10, 31)
CACHE = 'bt_cache_intraday'
M15 = 15 * 60 * 1000
COST = 0.10            # % andata e ritorno (commissioni taker + slippage stimati)
HORIZONS = (4, 16, 32)  # barre da 15m: 1 ora, 4 ore, 8 ore
WIN = 30 * 96           # finestra percentili: 30 giorni di barre 15m, solo passato
session = requests.Session()


def fetch(url):
    path = os.path.join(CACHE, url.replace(BASE + '/', '').replace('/', '_'))
    if os.path.exists(path):
        return open(path, 'rb').read() or None
    for i in range(4):
        try:
            r = session.get(url, timeout=30)
            if r.status_code == 404:
                open(path, 'wb').close(); return None
            if r.ok:
                open(path, 'wb').write(r.content); return r.content
        except Exception:
            pass
        time.sleep(1 + i * 2)
    return None


def rows(blob):
    if not blob:
        return []
    z = zipfile.ZipFile(io.BytesIO(blob))
    txt = z.read(z.namelist()[0]).decode()
    out = list(csv.reader(io.StringIO(txt)))
    if out and not out[0][0].lstrip('-').isdigit():
        out = out[1:]
    return out


def months():
    d = START.replace(day=1)
    while d <= END:
        yield d.strftime('%Y-%m')
        d = (d.replace(day=28) + timedelta(days=4)).replace(day=1)


def days():
    d = START
    while d <= END:
        yield d.isoformat(); d += timedelta(days=1)


def fnum(x):
    try:
        v = float(x)
        return None if math.isnan(v) else v
    except Exception:
        return None


def load(asset):
    s = asset + 'USDT'
    urls_k = [f'{BASE}/monthly/klines/{s}/15m/{s}-15m-{m}.zip' for m in months()]
    urls_f = [f'{BASE}/monthly/fundingRate/{s}/{s}-fundingRate-{m}.zip' for m in months()]
    urls_m = [f'{BASE}/daily/metrics/{s}/{s}-metrics-{d}.zip' for d in days()]
    with ThreadPoolExecutor(16) as ex:
        K = list(ex.map(fetch, urls_k)); F = list(ex.map(fetch, urls_f)); M = list(ex.map(fetch, urls_m))
    print(f'{asset}: klines {sum(1 for x in K if x)}/{len(K)} mesi, funding {sum(1 for x in F if x)}/{len(F)}, metrics {sum(1 for x in M if x)}/{len(M)} giorni', flush=True)
    bars = {}
    for b in K:
        for r in rows(b):
            t = int(r[0])
            bars[t] = {'t': t, 'o': float(r[1]), 'h': float(r[2]), 'l': float(r[3]), 'c': float(r[4]), 'v': float(r[5]), 'tb': float(r[9])}
    bars = [bars[k] for k in sorted(bars)]
    fund = sorted((int(r[0]), float(r[2]) * 100) for b in F for r in rows(b))
    met = {}
    for b in M:
        for r in rows(b):
            try:
                ts = int(datetime.strptime(r[0], '%Y-%m-%d %H:%M:%S').replace(tzinfo=timezone.utc).timestamp() * 1000)
                met[ts] = (fnum(r[3]), fnum(r[5]), fnum(r[6]), fnum(r[7]))
            except Exception:
                pass
    return bars, fund, met


def build(asset):
    bars, fund, met = load(asset)
    if len(bars) < 5000 or len(met) < 5000:
        return None
    mt = sorted(met)
    fi = mi = 0; fr = None; last_m = None; last_mt = None
    for b in bars:
        close = b['t'] + M15
        while fi < len(fund) and fund[fi][0] <= close:
            fr = fund[fi][1]; fi += 1
        while mi < len(mt) and mt[mi] <= close:
            last_m = met[mt[mi]]; last_mt = mt[mi]; mi += 1
        b['fr'] = fr
        fresh = last_m is not None and close - last_mt <= 30 * 60 * 1000  # metrics non più vecchie di 30 min
        b['oi'], b['ls_top'], b['ls_all'], b['taker'] = last_m if fresh else (None,) * 4
    atr = None
    for i, b in enumerate(bars):
        tr = b['h'] - b['l'] if i == 0 else max(b['h'] - b['l'], abs(b['h'] - bars[i - 1]['c']), abs(b['l'] - bars[i - 1]['c']))
        atr = tr if atr is None else (atr * 13 + tr) / 14
        b['atr'] = atr
    return bars


def pct(a, b):
    return (a / b - 1) * 100 if a and b else None


class RollRank:
    """Percentile di x rispetto agli ultimi W valori (solo passato)."""
    def __init__(self, w):
        self.w, self.q, self.s = w, deque(), []

    def rank_then_add(self, x):
        r = bisect.bisect_left(self.s, x) / len(self.s) if len(self.s) >= 500 else None
        self.q.append(x); bisect.insort(self.s, x)
        if len(self.q) > self.w:
            old = self.q.popleft(); del self.s[bisect.bisect_left(self.s, old)]
        return r


def features(B):
    F = []
    cv = [2 * b['tb'] - b['v'] for b in B]          # CVD vero per barra
    cp = [b['v'] if b['c'] >= b['o'] else -b['v'] for b in B]  # CVD "colore candela" come nel backend
    pre_cv = [0]; pre_cp = [0]
    for a, b in zip(cv, cp):
        pre_cv.append(pre_cv[-1] + a); pre_cp.append(pre_cp[-1] + b)
    for i, b in enumerate(B):
        f = {'i': i, 'fr': b['fr'], 'ls_top': b['ls_top'], 'ls_all': b['ls_all'], 'taker': b['taker']}
        if i >= 16:
            f['cvd_1h'] = pre_cv[i + 1] - pre_cv[i - 3]
            f['cvd_4h'] = pre_cv[i + 1] - pre_cv[i - 15]
            f['cvd_proxy_3h'] = pre_cp[i + 1] - pre_cp[i - 11]
            f['cvd_3h'] = pre_cv[i + 1] - pre_cv[i - 11]
            f['px_1h'] = pct(b['c'], B[i - 4]['c'])
            f['px_4h'] = pct(b['c'], B[i - 16]['c'])
            if b['oi'] and B[i - 4]['oi']:
                f['oi_1h'] = pct(b['oi'], B[i - 4]['oi'])
            if b['oi'] and B[i - 16]['oi']:
                f['oi_4h'] = pct(b['oi'], B[i - 16]['oi'])
            if b['oi'] and B[i - 1]['oi']:
                f['oi_15m'] = pct(b['oi'], B[i - 1]['oi'])
            vol4 = sum(x['v'] for x in B[i - 15:i + 1])
            f['cvd_4h_n'] = f['cvd_4h'] / vol4 if vol4 else None   # CVD normalizzato sul volume
        F.append(f)
    for key in ('fr', 'ls_top', 'ls_all', 'taker', 'oi_1h', 'cvd_4h_n', 'px_4h'):
        rr = RollRank(WIN)
        for f in F:
            x = f.get(key)
            f[key + '_rk'] = rr.rank_then_add(x) if x is not None else None
    return F


def sop_bias(f, cvd_key):
    """Bias del backend SOP, con OI su 4 ore invece che 20 ore."""
    if f.get('fr') is None or f.get('oi_4h') is None or f.get(cvd_key) is None:
        return None
    oi_t = 'up' if f['oi_4h'] > 1 else 'down' if f['oi_4h'] < -1 else 'flat'
    fr_t = 'pos' if f['fr'] > 0.05 else 'neg' if f['fr'] < -0.005 else 'neu'
    up, dn = f[cvd_key] > 0, f[cvd_key] < 0
    if fr_t == 'pos':
        return -1 if not up else 0
    if fr_t == 'neu':
        if oi_t == 'down':
            return 1 if up else 0
        return 1 if up else -1 if dn else 0
    if oi_t == 'down':
        return 1 if up else -1 if dn else 0
    return 1 if up else 0


def ext(rk, hi=0.95, lo=0.05):
    return None if rk is None else (1 if rk >= hi else -1 if rk <= lo else 0)


def g(f, *k):
    return all(f.get(x) is not None for x in k)


SIGNALS = {
    'SOP bias (come nel backend, CVD finto)': lambda f, b, B: sop_bias(f, 'cvd_proxy_3h'),
    'SOP bias con CVD vero': lambda f, b, B: sop_bias(f, 'cvd_3h'),
    'Funding estremo, contrarian': lambda f, b, B: (-ext(f['fr_rk'])) if f.get('fr_rk') is not None else None,
    'Long/short folla estremo, contrarian': lambda f, b, B: (-ext(f['ls_all_rk'])) if f.get('ls_all_rk') is not None else None,
    'Long/short top trader estremo, contrarian': lambda f, b, B: (-ext(f['ls_top_rk'])) if f.get('ls_top_rk') is not None else None,
    'Volume aggressivo estremo, segue': lambda f, b, B: ext(f['taker_rk']) if f.get('taker_rk') is not None else None,
    # OI che sale forte in 1h + CVD vero nella stessa direzione del prezzo: nuovi soldi, segue
    'OI in forte aumento + CVD concorde, segue': lambda f, b, B: ((1 if f['px_1h'] > 0 else -1) if f['oi_1h_rk'] >= 0.95 and f['cvd_1h'] * f['px_1h'] > 0 else 0) if g(f, 'oi_1h_rk', 'px_1h', 'cvd_1h') else None,
    # OI che crolla in 1h dopo un movimento (squeeze che si esaurisce): contrarian
    'OI in forte calo, contro il prezzo': lambda f, b, B: ((-1 if f['px_1h'] > 0 else 1) if f['oi_1h_rk'] <= 0.05 else 0) if g(f, 'oi_1h_rk', 'px_1h') else None,
    # divergenza: prezzo 4h ai massimi/minimi del mese ma CVD vero 4h opposto: contrarian
    'Divergenza prezzo/CVD vero, contrarian': lambda f, b, B: ((-1 if f['px_4h_rk'] >= 0.9 and f['cvd_4h_n_rk'] <= 0.3 else 1 if f['px_4h_rk'] <= 0.1 and f['cvd_4h_n_rk'] >= 0.7 else 0)) if g(f, 'px_4h_rk', 'cvd_4h_n_rk') else None,
    # liquidazioni (sostituto): barra 15m > 3 ATR con calo OI > 1% nella barra: rimbalzo contrario
    'Liquidazioni (sostituto), contrarian': lambda f, b, B: ((-1 if b['c'] > b['o'] else 1) if abs(b['c'] - b['o']) > 3 * B[f['i'] - 1]['atr'] and f['oi_15m'] < -1 else 0) if f['i'] > 0 and f.get('oi_15m') is not None else None,
    'Funding estremo + OI in aumento, contrarian': lambda f, b, B: ((-1 if f['fr_rk'] >= 0.9 else 1 if f['fr_rk'] <= 0.1 else 0) if f['oi_1h_rk'] >= 0.8 else 0) if g(f, 'fr_rk', 'oi_1h_rk') else None,
}


def evaluate(series):
    out = {}
    for name, fn in SIGNALS.items():
        res = {}
        for hz in HORIZONS:
            ev, base = [], []
            for a, (B, F) in series.items():
                busy = -1; n = len(B)
                for f in F:
                    i = f['i']
                    if i + 1 + hz >= n:
                        break
                    if B[i + hz]['t'] - B[i + 1]['t'] != (hz - 1) * M15:   # buchi nei dati
                        continue
                    raw = (B[i + hz]['c'] / B[i + 1]['o'] - 1) * 100
                    try:
                        d = fn(f, B[i], B)
                    except Exception:
                        d = None
                    if d is None:
                        continue
                    if i % hz == 0:
                        base.append(raw)
                    if d == 0 or i <= busy:
                        continue
                    ev.append((a, B[i]['t'], d, d * raw - COST))
                    busy = i + hz
            res[f'{hz * 15 // 60}h'] = stats(ev, base)
        out[name] = res
        print(name, {k: (v.get('n'), v.get('mean'), v.get('t')) for k, v in res.items()}, flush=True)
    return out


def summ(x):
    n = len(x)
    if n < 2:
        return {'n': n}
    m = sum(x) / n
    sd = math.sqrt(sum((v - m) ** 2 for v in x) / (n - 1))
    return {'n': n, 'mean': round(m, 3), 'hit': round(sum(1 for v in x if v > 0) / n, 3), 't': round(m / sd * math.sqrt(n), 2) if sd else 0}


def stats(ev, base):
    r = [e[3] for e in ev]
    mid = START + (END - START) / 2
    tmid = datetime(mid.year, mid.month, mid.day, tzinfo=timezone.utc).timestamp() * 1000
    s = summ(r)
    s['long'] = summ([e[3] for e in ev if e[2] > 0])
    s['short'] = summ([e[3] for e in ev if e[2] < 0])
    s['primo_anno'] = summ([e[3] for e in ev if e[1] < tmid])
    s['secondo_anno'] = summ([e[3] for e in ev if e[1] >= tmid])
    s['lordo'] = round(s['mean'] + COST, 3) if 'mean' in s else None
    if r and base:
        mb = sum(base) / len(base)
        share_long = sum(1 for e in ev if e[2] > 0) / len(ev)
        s['caso'] = round((2 * share_long - 1) * mb - COST, 3)
    per = {}
    for e in ev:
        per.setdefault(e[0], []).append(e[3])
    s['asset_positivi'] = sum(1 for v in per.values() if sum(v) > 0)
    s['asset'] = len(per)
    return s


def verdict(s):
    if s.get('n', 0) < 30:
        return 'troppo pochi casi'
    a, b = s['primo_anno'], s['secondo_anno']
    if s['mean'] > 0 and s['t'] >= 3 and a.get('mean', -1) > 0 and b.get('mean', -1) > 0 and s['asset_positivi'] >= 7:
        return 'VANTAGGIO (robusto)'
    if s['mean'] > 0 and s['t'] >= 2:
        return 'indizio positivo, non robusto'
    if s['mean'] < 0 and s['t'] <= -2:
        return 'PERDENTE'
    return 'nessun vantaggio'


def main():
    os.makedirs(CACHE, exist_ok=True)
    series = {}
    for a in ASSETS:
        B = build(a)
        if B:
            series[a] = (B, features(B))
    if not series:
        print('Nessun dato scaricato: archivio non raggiungibile.'); sys.exit(1)
    R = evaluate(series)
    json.dump({'periodo': [START.isoformat(), END.isoformat()], 'barre': '15m', 'asset': list(series), 'costo_pct': COST, 'risultati': R},
              open('backtest_intraday.json', 'w'), indent=1, ensure_ascii=False)
    nb = sum(len(B) for B, _ in series.values())
    f = lambda x: '—' if x is None else f'{x:+.2f}%'
    L = [f'# Backtest SOP intraday — squilibri dei derivati ({datetime.now(timezone.utc):%Y-%m-%d %H:%M} UTC)', '',
         f'Periodo {START:%d/%m/%Y} → {END:%d/%m/%Y}, barre da 15 minuti, futures perpetui Binance su {len(series)} crypto: {", ".join(series)} ({nb} barre in totale).',
         f'Ogni segnale entra all\'apertura della barra successiva ed esce dopo 1, 4 o 8 ore. Media netta di {COST}% di costi per operazione ("Lordo" = prima dei costi). Segnali non sovrapposti sullo stesso asset.',
         'Media = rendimento medio per operazione in %, nella direzione del segnale. t = forza statistica. "Caso" = stessa quota di long e short presi a caso.',
         'VANTAGGIO (robusto) solo se: media netta positiva, t ≥ 3, positivo in entrambi gli anni e su almeno 7 crypto su 10.', '',
         '| Segnale | Orizzonte | Casi | Vinte | Media netta | Lordo | t | 1° anno | 2° anno | Caso | Asset positivi | Giudizio |',
         '|---|---|---|---|---|---|---|---|---|---|---|---|']
    for name, res in R.items():
        for hz, s in res.items():
            if s.get('n', 0) < 2:
                L.append(f'| {name} | {hz} | {s.get("n", 0)} | | | | | | | | | troppo pochi casi |'); continue
            L.append(f'| {name} | {hz} | {s["n"]} | {s["hit"]*100:.0f}% | {f(s["mean"])} | {f(s.get("lordo"))} | {s["t"]} | {f(s["primo_anno"].get("mean"))} | {f(s["secondo_anno"].get("mean"))} | {f(s.get("caso"))} | {s["asset_positivi"]}/{s["asset"]} | {verdict(s)} |')
    L += ['', 'Liquidazioni: non sono nell\'archivio pubblico; il sostituto è una barra da 15 minuti oltre 3 ATR con calo dell\'open interest oltre l\'1%.',
          f'Attenzione: {len(SIGNALS)} segnali × {len(HORIZONS)} orizzonti = {len(SIGNALS) * len(HORIZONS)} prove. Per caso una o due possono sembrare buone: per questo la soglia è t ≥ 3 e la conferma su entrambi gli anni.',
          'Intraday i costi pesano molto: se un segnale è positivo al lordo ma negativo al netto, non è sfruttabile con ordini a mercato.']
    open('BACKTEST_INTRADAY.md', 'w').write('\n'.join(L) + '\n')
    print('\n'.join(L))


if __name__ == '__main__':
    main()
