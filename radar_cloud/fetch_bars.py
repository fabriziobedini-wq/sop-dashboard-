#!/usr/bin/env python3
"""Scarica le candele giornaliere per l'universo di Scopri (radar.html) senza TradingView.
Crypto: Binance spot (data-api.binance.vision). Azioni, ETF, materie prime: Yahoo Finance, con Stooq come riserva.
Scrive out/bars.json = {simbolo TradingView: [{t,o,h,l,c,v}, ...]} (t in secondi, apertura della barra)."""
import json, os, re, sys, time
import requests

HTML = os.path.join(os.path.dirname(__file__), 'radar.html')
OUT = os.path.join(os.path.dirname(__file__), 'out')
S = requests.Session(); S.headers['User-Agent'] = 'Mozilla/5.0 (radar-cloud)'
YSUF = {'MIL': '.MI', 'XETR': '.DE'}
EURONEXT = {'MC': 'MC.PA', 'ASML': 'ASML.AS'}
CMD = {'TVC:SILVER': 'SI=F', 'TVC:USOIL': 'CL=F', 'TVC:PLATINUM': 'PL=F', 'TVC:GOLD': 'GC=F', 'COMEX:HG1!': 'HG=F',
       'NYMEX:NG1!': 'NG=F', 'CBOT:ZS1!': 'ZS=F', 'CBOT:ZW1!': 'ZW=F', 'CBOT:ZC1!': 'ZC=F'}


def universe():
    src = open(HTML).read()
    m = re.search(r'const UNIVERSE = \[(.*?)\n  \];', src, re.S)
    body = m.group(1)
    syms = []
    c = re.search(r'\.\.\.\[(.*?)\]\.map\(t=>"BINANCE:"\+t\+"USDT"\)', body)
    syms += ['BINANCE:' + t + 'USDT' for t in re.findall(r'"([A-Z0-9]+)"', c.group(1))]
    rest = body[c.end():]
    syms += re.findall(r'"([A-Z0-9_]+:[A-Z0-9_.!]+)"', rest)
    return syms


def get(url, **kw):
    for i in range(3):
        try:
            r = S.get(url, timeout=25, **kw)
            if r.ok:
                return r
            if r.status_code in (400, 404):
                return None
        except Exception:
            pass
        time.sleep(2 + 3 * i)
    return None


def binance(sym):
    t = sym.split(':')[1]
    r = get('https://data-api.binance.vision/api/v3/klines', params={'symbol': t, 'interval': '1d', 'limit': 1000})
    if not r:
        return None
    return [{'t': k[0] // 1000, 'o': float(k[1]), 'h': float(k[2]), 'l': float(k[3]), 'c': float(k[4]), 'v': float(k[5])} for k in r.json()]


def ytick(sym):
    if sym in CMD:
        return CMD[sym]
    ex, t = sym.split(':')
    if ex == 'EURONEXT':
        return EURONEXT.get(t, t + '.PA')
    return t.replace('.', '-') + YSUF.get(ex, '')


def yahoo(sym):
    tk = ytick(sym)
    r = get(f'https://query1.finance.yahoo.com/v8/finance/chart/{tk}', params={'range': '5y', 'interval': '1d', 'includePrePost': 'false'})
    if not r:
        return None
    try:
        res = r.json()['chart']['result'][0]; q = res['indicators']['quote'][0]
        out = []
        for i, t in enumerate(res['timestamp']):
            o, h, l, c, v = q['open'][i], q['high'][i], q['low'][i], q['close'][i], q['volume'][i]
            if None in (o, h, l, c):
                continue
            out.append({'t': int(t), 'o': o, 'h': h, 'l': l, 'c': c, 'v': v or 0})
        return out[-1000:]
    except Exception:
        return None


def stooq(sym):
    ex, t = sym.split(':')
    if sym in CMD or ex not in ('NASDAQ', 'NYSE', 'AMEX'):
        return None
    r = get(f'https://stooq.com/q/d/l/?s={t.lower()}.us&i=d')
    if not r or not r.text.startswith('Date'):
        return None
    out = []
    for line in r.text.strip().splitlines()[1:]:
        d, o, h, l, c, *v = line.split(',')
        tt = int(time.mktime(time.strptime(d, '%Y-%m-%d'))) + 48600
        out.append({'t': tt, 'o': float(o), 'h': float(h), 'l': float(l), 'c': float(c), 'v': float(v[0]) if v else 0})
    return out[-1000:]


def main():
    os.makedirs(OUT, exist_ok=True)
    extra = sys.argv[1:]
    syms = list(dict.fromkeys(universe() + ['TVC:GOLD'] + extra))
    bars, miss = {}, []
    for s in syms:
        b = binance(s) if s.startswith('BINANCE:') else (yahoo(s) or stooq(s))
        if b and len(b) >= 90:
            bars[s] = b
        else:
            miss.append(s)
        time.sleep(0.3)
    json.dump(bars, open(os.path.join(OUT, 'bars.json'), 'w'))
    print(f'candele scaricate per {len(bars)}/{len(syms)} simboli; mancanti: {", ".join(miss) or "nessuno"}')


if __name__ == '__main__':
    main()
