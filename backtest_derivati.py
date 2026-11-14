#!/usr/bin/env python3
"""
Backtest del livello "derivati" del metodo SOP: squilibri di open interest,
volume aggressivo (CVD), funding, rapporto long/short e liquidazioni.

Domanda: questi squilibri anticipano la direzione del prezzo nelle 24-72 ore
successive, più di quanto farebbe il caso? Solo misura statistica:
nessun ordine, nessun broker, nessuna chiave API.

Dati: archivio pubblico Binance Futures USDⓈ-M (data.binance.vision)
  - klines 1h (con volume aggressivo in acquisto: taker buy volume) -> barre 4h
  - metrics 5 minuti: open interest, rapporto long/short (top trader e tutti),
    rapporto volume aggressivo acquisto/vendita
  - funding rate storico
Le liquidazioni non sono nell'archivio: si usa un sostituto (barra da 4h con
movimento > 2,5 ATR e calo dell'open interest > 2% nella stessa barra).
"""
import csv, io, json, math, os, sys, time, zipfile
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta, timezone
import requests

BASE = 'https://data.binance.vision/data/futures/um'
ASSETS = ['BTC', 'ETH', 'SOL', 'XRP', 'BNB', 'DOGE', 'ADA', 'LINK', 'AVAX', 'TRX']
START = date(2024, 11, 1)
END = date(2026, 10, 31)
CACHE = 'bt_cache'
H4 = 4 * 3600 * 1000
COST = 0.10          # % andata e ritorno (commissioni + slippage stimati)
HORIZONS = (6, 18)   # barre da 4h: 24 ore e 72 ore
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


def load(asset):
    s = asset + 'USDT'
    cur = END.strftime('%Y-%m')
    urls_k = [f'{BASE}/monthly/klines/{s}/1h/{s}-1h-{m}.zip' for m in months() if m != cur or END.month != (END + timedelta(days=1)).month]
    if END.month == (END + timedelta(days=1)).month:  # mese in corso: file giornalieri
        urls_k += [f'{BASE}/daily/klines/{s}/1h/{s}-1h-{d}.zip' for d in days() if d.startswith(cur)]
    urls_f = [f'{BASE}/monthly/fundingRate/{s}/{s}-fundingRate-{m}.zip' for m in months()]
    urls_m = [f'{BASE}/daily/metrics/{s}/{s}-metrics-{d}.zip' for d in days()]
    with ThreadPoolExecutor(16) as ex:
        K = list(ex.map(fetch, urls_k)); F = list(ex.map(fetch, urls_f)); M = list(ex.map(fetch, urls_m))
    print(f'{asset}: klines {sum(1 for x in K if x)}/{len(K)} mesi, funding {sum(1 for x in F if x)}/{len(F)}, metrics {sum(1 for x in M if x)}/{len(M)} giorni', flush=True)
    # barre 4h dalle 1h
    bars = {}
    for b in K:
        for r in rows(b):
            t = int(r[0]); t4 = t - t % H4
            o, h, l, c, v, tb = float(r[1]), float(r[2]), float(r[3]), float(r[4]), float(r[5]), float(r[9])
            x = bars.get(t4)
            if x is None:
                bars[t4] = {'t': t4, 'o': o, 'h': h, 'l': l, 'c': c, 'v': v, 'tb': tb, 'n': 1}
            else:
                x['h'] = max(x['h'], h); x['l'] = min(x['l'], l); x['c'] = c; x['v'] += v; x['tb'] += tb; x['n'] += 1
    bars = [bars[k] for k in sorted(bars) if bars[k]['n'] == 4]
    fund = sorted((int(r[0]), float(r[2]) * 100) for b in F for r in rows(b))
    met = {}
    for b in M:
        for r in rows(b):
            try:
                ts = int(datetime.strptime(r[0], '%Y-%m-%d %H:%M:%S').replace(tzinfo=timezone.utc).timestamp() * 1000)
                met[ts] = (float(r[3]), float(r[5] or 'nan'), float(r[6] or 'nan'), float(r[7] or 'nan'))
            except Exception:
                pass
    return bars, fund, met


def build(asset):
    bars, fund, met = load(asset)
    if len(bars) < 500 or len(met) < 1000:
        return None
    mt = sorted(met)
    fi = mi = 0; fr = None; last_m = None
    for b in bars:
        close = b['t'] + H4  # istante di chiusura della barra
        while fi < len(fund) and fund[fi][0] <= close:
            fr = fund[fi][1]; fi += 1
        while mi < len(mt) and mt[mi] <= close:
            last_m = met[mt[mi]]; mi += 1
        b['fr'] = fr
        b['oi'], b['ls_top'], b['ls_all'], b['taker'] = last_m if last_m else (None,) * 4
    # ATR 14
    atr = None
    for i, b in enumerate(bars):
        tr = b['h'] - b['l'] if i == 0 else max(b['h'] - b['l'], abs(b['h'] - bars[i - 1]['c']), abs(b['l'] - bars[i - 1]['c']))
        atr = tr if atr is None else (atr * 13 + tr) / 14
        b['atr'] = atr
    return bars


def pct(a, b):
    return (a / b - 1) * 100 if a and b else None


def rank(hist, x):
    if x is None or len(hist) < 100:
        return None
    return sum(1 for h in hist if h < x) / len(hist)


def features(bars):
    """Per ogni barra chiusa i, solo informazioni disponibili alla chiusura."""
    F = []
    for i in range(len(bars)):
        b = bars[i]
        f = {'i': i}
        if i >= 12:
            sl = bars[i - 11:i + 1]
            f['cvd_proxy'] = sum(x['v'] if x['c'] >= x['o'] else -x['v'] for x in sl)
            f['cvd'] = sum(2 * x['tb'] - x['v'] for x in sl)
        if i >= 5 and b['oi'] and bars[i - 5]['oi']:
            f['oi_d20h'] = pct(b['oi'], bars[i - 5]['oi'])
        if i >= 6 and b['oi'] and bars[i - 6]['oi']:
            f['oi_d24h'] = pct(b['oi'], bars[i - 6]['oi'])
            f['px_d24h'] = pct(b['c'], bars[i - 6]['c'])
        if i >= 1 and b['oi'] and bars[i - 1]['oi']:
            f['oi_d4h'] = pct(b['oi'], bars[i - 1]['oi'])
        f['fr'] = b['fr']
        f['ls_top'] = b['ls_top']; f['ls_all'] = b['ls_all']; f['taker'] = b['taker']
        F.append(f)
    # percentili su finestra mobile di 90 giorni (540 barre), solo passato
    W = 540
    for key in ('fr', 'ls_top', 'ls_all', 'taker', 'oi_d24h'):
        hist = []
        for f in F:
            x = f.get(key)
            f[key + '_rk'] = rank(hist[-W:], x) if x is not None and not (isinstance(x, float) and math.isnan(x)) else None
            if x is not None and not (isinstance(x, float) and math.isnan(x)):
                hist.append(x)
    return F


def sop_bias(f, cvd_key):
    if f.get('fr') is None or f.get('oi_d20h') is None or f.get(cvd_key) is None:
        return None
    oi_t = 'up' if f['oi_d20h'] > 1 else 'down' if f['oi_d20h'] < -1 else 'flat'
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


SIGNALS = {
    # il bias del backend SOP, identico al codice (CVD = colore delle candele, come nel backend)
    'SOP bias (come nel backend)': lambda f, b, B: sop_bias(f, 'cvd_proxy'),
    # stesso bias con il CVD vero (volume aggressivo in acquisto meno vendita)
    'SOP bias con CVD vero': lambda f, b, B: sop_bias(f, 'cvd'),
    # funding estremo: contrarian (troppi long pagano -> short, e viceversa)
    'Funding estremo, contrarian': lambda f, b, B: (-1 if f['fr_rk'] >= 0.95 else 1 if f['fr_rk'] <= 0.05 else 0) if f.get('fr_rk') is not None else None,
    # rapporto long/short dei top trader estremo: contrarian
    'Long/short top trader estremo, contrarian': lambda f, b, B: (-1 if f['ls_top_rk'] >= 0.95 else 1 if f['ls_top_rk'] <= 0.05 else 0) if f.get('ls_top_rk') is not None else None,
    # rapporto long/short di tutti i conti estremo: contrarian (la folla sbaglia)
    'Long/short folla estremo, contrarian': lambda f, b, B: (-1 if f['ls_all_rk'] >= 0.95 else 1 if f['ls_all_rk'] <= 0.05 else 0) if f.get('ls_all_rk') is not None else None,
    # volume aggressivo estremo: segue la direzione
    'Volume aggressivo estremo, segue': lambda f, b, B: (1 if f['taker_rk'] >= 0.95 else -1 if f['taker_rk'] <= 0.05 else 0) if f.get('taker_rk') is not None else None,
    # OI sale forte con prezzo in salita: nuovi long, segue
    'OI in forte aumento, segue il prezzo': lambda f, b, B: ((1 if f['px_d24h'] > 0 else -1) if f['oi_d24h_rk'] >= 0.9 else 0) if f.get('oi_d24h_rk') is not None and f.get('px_d24h') is not None else None,
    # OI crolla dopo un movimento: chiusure forzate, contrarian
    'OI in forte calo, contro il prezzo': lambda f, b, B: ((-1 if f['px_d24h'] > 0 else 1) if f['oi_d24h_rk'] <= 0.1 else 0) if f.get('oi_d24h_rk') is not None and f.get('px_d24h') is not None else None,
    # sostituto liquidazioni: barra > 2,5 ATR con calo OI > 2% -> rimbalzo contrario
    'Liquidazioni (sostituto), contrarian': lambda f, b, B: ((-1 if b['c'] > b['o'] else 1) if abs(b['c'] - b['o']) > 2.5 * B[f['i'] - 1]['atr'] and f['oi_d4h'] < -2 else 0) if f['i'] > 0 and f.get('oi_d4h') is not None else None,
    # funding estremo + OI che sale (squilibrio che si accumula): contrarian
    'Funding estremo + OI in aumento, contrarian': lambda f, b, B: ((-1 if f['fr_rk'] >= 0.9 else 1 if f['fr_rk'] <= 0.1 else 0) if (f['oi_d24h_rk'] or 0) >= 0.7 else 0) if f.get('fr_rk') is not None and f.get('oi_d24h_rk') is not None else None,
}


def evaluate(series):
    """series: {asset: (bars, feats)} -> risultati per segnale e orizzonte."""
    out = {}
    for name, fn in SIGNALS.items():
        res = {}
        for hz in HORIZONS:
            ev = []  # (asset, t, dir, ret_netto_%)
            base = []
            for a, (B, F) in series.items():
                busy_until = -1
                n = len(B)
                for f in F:
                    i = f['i']
                    if i + 1 + hz >= n:
                        break
                    entry = B[i + 1]['o']; exitp = B[i + hz]['c']
                    raw = (exitp / entry - 1) * 100
                    try:
                        d = fn(f, B[i], B)
                    except Exception:
                        d = None
                    if d is None:
                        continue
                    base.append(raw)
                    if d == 0 or i <= busy_until:
                        continue
                    ev.append((a, B[i]['t'], d, d * raw - COST))
                    busy_until = i + hz  # niente segnali sovrapposti sullo stesso asset
            res[f'{hz * 4}h'] = stats(ev, base)
        out[name] = res
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
    # confronto: stessa direzione presa a caso (media del mercato nel periodo, segno medio dei segnali)
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
    if s['mean'] > 0 and s['t'] >= 2.5 and a.get('mean', -1) > 0 and b.get('mean', -1) > 0:
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
    json.dump({'periodo': [START.isoformat(), END.isoformat()], 'asset': list(series), 'costo_pct': COST, 'risultati': R}, open('backtest_derivati.json', 'w'), indent=1, ensure_ascii=False)
    nb = sum(len(B) for B, _ in series.values())
    L = [f'# Backtest SOP — squilibri dei derivati ({datetime.now(timezone.utc):%Y-%m-%d %H:%M} UTC)', '',
         f'Periodo {START:%d/%m/%Y} → {END:%d/%m/%Y}, barre da 4 ore, futures perpetui Binance su {len(series)} crypto: {", ".join(series)} ({nb} barre in totale).',
         f'Ogni segnale entra all\'apertura della barra successiva ed esce dopo 24 o 72 ore. Risultato netto di {COST}% di costi. Segnali non sovrapposti sullo stesso asset.',
         'Media = rendimento medio per operazione in %, nella direzione del segnale. t = forza statistica (sopra 2,5 e positivo in entrambi gli anni = vantaggio robusto). "Caso" = cosa avresti ottenuto con la stessa quota di long e short presi a caso.', '',
         '| Segnale | Orizzonte | Casi | Vinte | Media | t | 1° anno | 2° anno | Caso | Asset positivi | Giudizio |', '|---|---|---|---|---|---|---|---|---|---|---|']
    for name, res in R.items():
        for hz, s in res.items():
            if s.get('n', 0) < 2:
                L.append(f'| {name} | {hz} | {s.get("n", 0)} | | | | | | | | troppo pochi casi |'); continue
            f = lambda x: '—' if x is None else f'{x:+.2f}%'
            L.append(f'| {name} | {hz} | {s["n"]} | {s["hit"]*100:.0f}% | {f(s["mean"])} | {s["t"]} | {f(s["primo_anno"].get("mean"))} | {f(s["secondo_anno"].get("mean"))} | {f(s.get("caso"))} | {s["asset_positivi"]}/{s["asset"]} | {verdict(s)} |')
    L += ['', 'Le liquidazioni non sono nell\'archivio pubblico: il segnale "Liquidazioni (sostituto)" usa una barra con movimento oltre 2,5 ATR e calo dell\'open interest oltre il 2%.',
          'Attenzione: sono 10 segnali × 2 orizzonti = 20 prove. Per puro caso una su venti può sembrare buona: conta solo un risultato forte (t ≥ 2,5) e positivo in entrambi gli anni.']
    open('BACKTEST_DERIVATI.md', 'w').write('\n'.join(L) + '\n')
    print('\n'.join(L))


if __name__ == '__main__':
    main()
