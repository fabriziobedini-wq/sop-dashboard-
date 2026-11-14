#!/usr/bin/env python3
"""Fotografia del giorno sulle crypto: dove si sta spostando il denaro nei derivati.
Usa solo i due segnali che hanno passato il backtest (BACKTEST_DERIVATI.md):
  1) liquidazioni (sostituto): candela 4h oltre 2,5 ATR con OI in calo oltre il 2% -> entrata contraria, 72 ore
  2) long/short della folla estremo (percentile 95/5 sugli ultimi 90 giorni) -> entrata contraria, 72 ore
Il resto (funding, OI, volume aggressivo/CVD, liquidazioni reali OKX) è solo contesto: da solo non ha vantaggio.
Dati: archivio Binance Futures fino a ieri (data.binance.vision) + istantanea OKX in tempo reale.
Nessun ordine, nessuna chiave API."""
import json, math, os, time
from datetime import date, datetime, timedelta, timezone
import requests
import backtest_derivati as bd

ASSETS = ['BTC', 'ETH', 'SOL', 'XRP', 'BNB', 'DOGE', 'ADA', 'LINK', 'AVAX', 'TRX', 'SUI', 'LTC']
bd.END = date.today() - timedelta(days=1)
bd.START = bd.END - timedelta(days=130)
OKX = 'https://www.okx.com/api/v5'
S = requests.Session()


def okx(path, **params):
    try:
        r = S.get(OKX + path, params=params, timeout=20)
        j = r.json()
        return j.get('data') if j.get('code') == '0' else None
    except Exception:
        return None


def okx_snapshot(a):
    inst = f'{a}-USDT-SWAP'
    out = {}
    t = okx('/market/ticker', instId=inst)
    if t:
        out['prezzo'] = float(t[0]['last'])
        o24 = float(t[0]['open24h'] or 0)
        out['var_24h'] = round((out['prezzo'] / o24 - 1) * 100, 2) if o24 else None
    f = okx('/public/funding-rate', instId=inst)
    if f:
        out['funding_pct'] = round(float(f[0]['fundingRate']) * 100, 4)
    ls = okx('/rubik/stat/contracts/long-short-account-ratio-contract', instId=inst, period='1H', limit='24')
    if ls:
        out['ls_folla_okx'] = round(float(ls[0][1]), 2)
        out['ls_folla_okx_24h_fa'] = round(float(ls[-1][1]), 2)
    tv = okx('/rubik/stat/taker-volume-contract', instId=inst, period='1H', unit='2', limit='24')
    if tv:
        buy = sum(float(x[2]) for x in tv); sell = sum(float(x[1]) for x in tv)
        out['cvd_24h_usd_mln'] = round((buy - sell) / 1e6, 1)
        out['acquisti_aggressivi_pct'] = round(buy / (buy + sell) * 100, 1) if buy + sell else None
    oi = okx('/rubik/stat/contracts/open-interest-history', instId=inst, period='1H', limit='25')
    if oi and len(oi) >= 25:
        now, before = float(oi[0][3]), float(oi[24][3])
        out['oi_usd_mln'] = round(now / 1e6, 0)
        out['oi_var_24h_pct'] = round((now / before - 1) * 100, 2) if before else None
    liq = okx('/public/liquidation-orders', instType='SWAP', instFamily=f'{a}-USDT', state='filled', limit='100')
    if liq:
        cut = time.time() * 1000 - 24 * 3600 * 1000
        lo = sh = 0.0
        ctv = 1.0
        ins = okx('/public/instruments', instType='SWAP', instId=inst)
        if ins:
            ctv = float(ins[0]['ctVal'])
        for blk in liq:
            for d in blk.get('details', []):
                if int(d['ts']) < cut:
                    continue
                usd = float(d['sz']) * ctv * float(d['bkPx'])
                # side sell = liquidato un long, buy = liquidato uno short
                if d['side'] == 'sell':
                    lo += usd
                else:
                    sh += usd
        out['liq_long_24h_usd_mln'] = round(lo / 1e6, 2)
        out['liq_short_24h_usd_mln'] = round(sh / 1e6, 2)
    return out


def okx_funding_hist(a):
    """Funding storico OKX (ultimi ~100 pagamenti) per coprire il mese in corso, che Binance pubblica solo a fine mese."""
    d = okx('/public/funding-rate-history', instId=f'{a}-USDT-SWAP', limit='100')
    return [(int(x['fundingTime']), float(x['realizedRate'] or x['fundingRate']) * 100) for x in d or []]


_load = bd.load
def load_plus(a):
    bars, fund, met = _load(a)
    last = fund[-1][0] if fund else 0
    fund = sorted(fund + [x for x in okx_funding_hist(a) if x[0] > last])
    return bars, fund, met
bd.load = load_plus


def main():
    os.makedirs(bd.CACHE, exist_ok=True)
    res = {'creato': datetime.now(timezone.utc).isoformat(timespec='minutes'), 'archivio_fino_a': bd.END.isoformat(), 'asset': {}}
    for a in ASSETS:
        B = bd.build(a)
        row = {}
        if B:
            F = bd.features(B)
            f, b = F[-1], B[-1]
            last_t = b['t'] + bd.H4
            row['archivio_ultima_candela'] = datetime.fromtimestamp(last_t / 1000, timezone.utc).strftime('%d/%m %H:%M UTC')
            row['ls_folla_binance'] = round(f['ls_all'], 2) if f.get('ls_all') == f.get('ls_all') else None
            row['ls_folla_percentile_90g'] = round(f['ls_all_rk'] * 100) if f.get('ls_all_rk') is not None else None
            row['funding_percentile_90g'] = round(f['fr_rk'] * 100) if f.get('fr_rk') is not None else None
            row['acquisti_aggressivi_percentile_90g'] = round(f['taker_rk'] * 100) if f.get('taker_rk') is not None else None
            row['oi_var_24h_percentile_90g'] = round(f['oi_d24h_rk'] * 100) if f.get('oi_d24h_rk') is not None else None
            # segnali validati nelle ultime 72 ore (18 candele da 4h)
            sig = []
            for ff in F[-18:]:
                i = ff['i']; bb = B[i]
                liq = bd.SIGNALS['Liquidazioni (sostituto), contrarian'](ff, bb, B)
                crowd = bd.SIGNALS['Long/short folla estremo, contrarian'](ff, bb, B)
                for name, d in (('liquidazioni', liq), ('folla estrema', crowd)):
                    if d:
                        sig.append({'segnale': name, 'lato': 'long' if d > 0 else 'short',
                                    'quando': datetime.fromtimestamp((bb['t'] + bd.H4) / 1000, timezone.utc).strftime('%d/%m %H:%M UTC'),
                                    'prezzo_segnale': bb['c'], 'scade': datetime.fromtimestamp((bb['t'] + bd.H4 + 72 * 3600000) / 1000, timezone.utc).strftime('%d/%m %H:%M UTC')})
            # tieni solo l'ultimo per tipo
            last = {}
            for s in sig:
                last[s['segnale']] = s
            row['segnali_validati_72h'] = list(last.values())
            row['crowd_oggi'] = 'short (folla troppo long)' if (f.get('ls_all_rk') or 0.5) >= 0.95 else 'long (folla troppo short)' if (f.get('ls_all_rk') or 0.5) <= 0.05 else 'nessuno'
        row['okx_ora'] = okx_snapshot(a)
        res['asset'][a] = row
        print(a, json.dumps(row, ensure_ascii=False), flush=True)
    os.makedirs('oggi', exist_ok=True)
    json.dump(res, open('oggi/crypto_oggi.json', 'w'), ensure_ascii=False, indent=1)


if __name__ == '__main__':
    main()
