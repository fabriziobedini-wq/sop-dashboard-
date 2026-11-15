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
    for i in range(4):
        try:
            r = S.get(OKX + path, params=params, timeout=20)
            j = r.json()
            if j.get('code') == '0':
                time.sleep(0.5)
                return j.get('data')
            print('OKX', path, params.get('instId') or params.get('instFamily'), j.get('code'), j.get('msg'), flush=True)
        except Exception as e:
            print('OKX errore', path, e, flush=True)
        time.sleep(2 + 2 * i)
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


def live_liq(a):
    """Segnale liquidazioni in tempo reale su OKX: ultime candele 4h chiuse (UTC) + open interest orario."""
    inst = f'{a}-USDT-SWAP'
    c = okx('/market/history-candles', instId=inst, bar='4H', limit='40')
    oi = okx('/rubik/stat/contracts/open-interest-history', instId=inst, period='1H', limit='100')
    if not c or not oi:
        return None
    C = sorted([(int(x[0]), float(x[1]), float(x[2]), float(x[3]), float(x[4])) for x in c if x[8] == '1'])
    OI = {int(x[0]): float(x[3]) for x in oi}
    atr = None; out = []
    for i, (t, o, h, l, cl) in enumerate(C):
        prev_atr = atr
        tr = h - l if i == 0 else max(h - l, abs(h - C[i - 1][4]), abs(l - C[i - 1][4]))
        atr = tr if atr is None else (atr * 13 + tr) / 14
        o0, o1 = OI.get(t), OI.get(t + 4 * 3600000)
        if i < 15 or not prev_atr or not o0 or not o1:
            continue
        oi_ch = (o1 / o0 - 1) * 100
        if abs(cl - o) > 2.5 * prev_atr and oi_ch < -2:
            out.append({'segnale': 'liquidazioni (tempo reale OKX)', 'lato': 'long' if cl < o else 'short',
                        'quando': datetime.fromtimestamp((t + 4 * 3600000) / 1000, timezone.utc).strftime('%d/%m %H:%M UTC'),
                        'chiusura_ts': t + 4 * 3600000, 'prezzo_segnale': cl, 'oi_var_pct': round(oi_ch, 1), 'atr': round(prev_atr, 6),
                        'scade': datetime.fromtimestamp((t + 4 * 3600000 + 72 * 3600000) / 1000, timezone.utc).strftime('%d/%m %H:%M UTC')})
    # massimo dell'OI negli ultimi ~4 giorni, per misurare quanta leva è già uscita
    vals = [x[1] for x in sorted(OI.items())]
    ctx = {'oi_dal_massimo_4g_pct': round((vals[-1] / max(vals) - 1) * 100, 1) if vals else None}
    if C:
        last = C[-1]
        e20 = None
        for x in C:
            e20 = x[4] if e20 is None else x[4] * 2 / 21 + e20 * 19 / 21
        ctx['sopra_media20_4h'] = last[4] > e20
        lows = [x[3] for x in C[-12:]]
        ctx['minimo_crescente_4h'] = len(C) >= 12 and min(lows[-6:]) > min(lows[:6])
    return {'segnali': out[-1:], 'contesto': ctx}


# ---- budget di rischio (PASS/BLOCK), deciso una volta sola quando il segnale entra nel registro ----
MAX_OPEN, MAX_SAME_SIDE, MAX_PER_DAY, WEEK_STOP_R = 3, 2, 2, -3.0


def k_atr(segnale):
    try:
        mc = json.load(open('montecarlo_futures.json'))
        return float(mc[segnale]['k_atr'])
    except Exception:
        return 3.0


def budget(reg):
    for r in reg:  # R e unità di rischio per tutti
        if not r.get('atr') and r.get('stop_indicativo'):
            r['atr'] = round(abs(r['entrata'] - r['stop_indicativo']) / 2, 6)
        r.pop('stop_indicativo', None); r.pop('stop_toccato', None)
        if r.get('atr'):
            r['k_atr'] = r.get('k_atr') or k_atr(r['segnale'])
            r['rischio_pct_prezzo'] = round(r['k_atr'] * r['atr'] / r['entrata'] * 100, 2)
            if r.get('risultato_pct') is not None:
                r['risultato_R'] = round(r['risultato_pct'] / r['rischio_pct_prezzo'], 2)
    ordered = sorted(reg, key=lambda z: (z['chiusura_ts'], z['asset']))
    for r in ordered:
        if r.get('decisione'):
            continue
        t = r['chiusura_ts']
        live = [q for q in ordered if q is not r and q.get('decisione') == 'PASS' and q['chiusura_ts'] <= t < q['scade_ts']]
        today = [q for q in ordered if q is not r and q.get('decisione') == 'PASS' and t - 86400000 < q['chiusura_ts'] <= t]
        week = sum(q.get('risultato_R') or 0 for q in ordered if q.get('decisione') == 'PASS' and q['scade_ts'] <= t and t - q['scade_ts'] < 7 * 86400000)
        why = None
        if any(q['asset'] == r['asset'] for q in live): why = f"c'è già un segnale aperto su {r['asset']}"
        elif len(live) >= MAX_OPEN: why = f"già {MAX_OPEN} segnali aperti"
        elif sum(1 for q in live if q['lato'] == r['lato']) >= MAX_SAME_SIDE: why = f"già {MAX_SAME_SIDE} segnali {r['lato']} aperti: le crypto si muovono insieme"
        elif len(today) >= MAX_PER_DAY: why = f"già {MAX_PER_DAY} segnali nelle ultime 24 ore"
        elif week <= WEEK_STOP_R: why = f"perdita della settimana {week:+.1f} R: stop settimanale a {WEEK_STOP_R:.0f} R"
        r['decisione'] = 'BLOCK' if why else 'PASS'
        r['motivo'] = why or 'dentro il budget'


def send_tg(msg):
    tok, chat = os.environ.get('TG_TOKEN'), os.environ.get('TG_CHAT')
    if not tok or not chat:
        print('[TG]', msg); return
    try:
        S.post(f'https://api.telegram.org/bot{tok}/sendMessage', json={'chat_id': chat, 'text': msg, 'parse_mode': 'HTML'}, timeout=10)
    except Exception as e:
        print('TG error', e)


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
                        sig.append({'segnale': name, 'lato': 'long' if d > 0 else 'short', 'chiusura_ts': bb['t'] + bd.H4, 'atr': round(B[i - 1]['atr'], 6),
                                    'quando': datetime.fromtimestamp((bb['t'] + bd.H4) / 1000, timezone.utc).strftime('%d/%m %H:%M UTC'),
                                    'prezzo_segnale': bb['c'], 'scade': datetime.fromtimestamp((bb['t'] + bd.H4 + 72 * 3600000) / 1000, timezone.utc).strftime('%d/%m %H:%M UTC')})
            # tieni solo l'ultimo per tipo
            last = {}
            for s in sig:
                last[s['segnale']] = s
            row['segnali_validati_72h'] = list(last.values())
            row['crowd_oggi'] = 'short (folla troppo long)' if (f.get('ls_all_rk') or 0.5) >= 0.95 else 'long (folla troppo short)' if (f.get('ls_all_rk') or 0.5) <= 0.05 else 'nessuno'
        row['okx_ora'] = okx_snapshot(a)
        lv = live_liq(a)
        if lv:
            row['contesto_4h'] = lv['contesto']
            row['segnali_validati_72h'] = [x for x in row.get('segnali_validati_72h', []) if x['segnale'] != 'liquidazioni'] + lv['segnali']
        # checklist "fine della discesa": solo descrittiva, tranne la cascata di liquidazioni (validata)
        o = row['okx_ora']; c4 = row.get('contesto_4h', {})
        row['checklist_ripartenza'] = {
            'cascata_liquidazioni_long': any(x['lato'] == 'long' and 'liquidazioni' in x['segnale'] for x in row.get('segnali_validati_72h', [])),
            'folla_non_piu_long_estrema': (row.get('ls_folla_percentile_90g') or 100) < 70,
            'leva_scaricata_oi_-10pct': (c4.get('oi_dal_massimo_4g_pct') or 0) <= -10,
            'funding_negativo': (o.get('funding_pct') or 0) < 0,
            'acquisti_aggressivi_tornano': (o.get('acquisti_aggressivi_pct') or 0) > 51,
            'prezzo_sopra_media20_4h': bool(c4.get('sopra_media20_4h')),
            'minimo_crescente_4h': bool(c4.get('minimo_crescente_4h')),
        }
        res['asset'][a] = row
        print(a, json.dumps(row, ensure_ascii=False), flush=True)
    os.makedirs('oggi', exist_ok=True)
    json.dump(res, open('oggi/crypto_oggi.json', 'w'), ensure_ascii=False, indent=1)
    # registro dei segnali futures: regola testata = entrata al prezzo del segnale, uscita dopo 72 ore
    reg_p = 'oggi/segnali_futures.json'
    reg = json.load(open(reg_p)) if os.path.exists(reg_p) else []
    known = {(r['asset'], r['segnale'].split(' (')[0], r['chiusura_ts']) for r in reg}
    for a, r in res['asset'].items():
        for x in r.get('segnali_validati_72h', []):
            k = (a, x['segnale'].split(' (')[0], x.get('chiusura_ts'))
            if not x.get('chiusura_ts') or k in known:
                continue
            known.add(k)
            d = 1 if x['lato'] == 'long' else -1
            atr = x.get('atr') or 0
            reg.append({'asset': a, 'segnale': x['segnale'].split(' (')[0], 'lato': x['lato'], 'chiusura_ts': x['chiusura_ts'],
                        'quando': x['quando'], 'entrata': x['prezzo_segnale'], 'scade_ts': x['chiusura_ts'] + 72 * 3600000,
                        'atr': atr or None, 'stato': 'aperto'})
    now = time.time() * 1000
    for r in reg:
        if r['stato'] != 'aperto':
            continue
        c = okx('/market/history-candles', instId=f"{r['asset']}-USDT-SWAP", bar='1H', limit='100')
        if not c:
            continue
        C = sorted([(int(x[0]), float(x[2]), float(x[3]), float(x[4])) for x in c if x[8] == '1'])
        d = 1 if r['lato'] == 'long' else -1
        after = [x for x in C if x[0] >= r['chiusura_ts'] and x[0] + 3600000 <= r['scade_ts']]
        if not after:
            continue
        e = r['entrata']
        r['prezzo_attuale'] = after[-1][3]
        r['risultato_pct'] = round(d * (after[-1][3] / e - 1) * 100, 2)
        worst = min(d * ((x[2] if d > 0 else x[1]) / e - 1) * 100 for x in after)
        best = max(d * ((x[1] if d > 0 else x[2]) / e - 1) * 100 for x in after)
        r['peggiore_pct'] = round(min(worst, r.get('peggiore_pct', 0)), 2)
        r['migliore_pct'] = round(max(best, r.get('migliore_pct', 0)), 2)
        if now >= r['scade_ts'] and after[-1][0] + 3600000 >= r['scade_ts'] - 3600000:
            r['stato'] = 'chiuso'
    budget(reg)
    json.dump(reg, open(reg_p, 'w'), ensure_ascii=False, indent=1)

    # avvisi Telegram solo per i segnali validati nuovi
    sent_p = 'oggi/avvisi_inviati.json'
    sent = json.load(open(sent_p)) if os.path.exists(sent_p) else []
    for a, r in res['asset'].items():
        for x in r.get('segnali_validati_72h', []):
            key = f"{a}|{x['segnale']}|{x['quando']}"
            if key in sent:
                continue
            sent.append(key)
            ck = r.get('checklist_ripartenza', {})
            rr = next((q for q in reg if q['asset'] == a and q['chiusura_ts'] == x.get('chiusura_ts')), {})
            send_tg(f"<b>Crypto: segnale validato</b>\n{a} — <b>{x['lato'].upper()}</b> ({x['segnale']})\n"
                    f"Entrata {x['prezzo_segnale']} (candela del {x['quando']}). Uscita dopo 72 ore: {x['scade']}.\n"
                    f"Budget: <b>{rr.get('decisione', '?')}</b> ({rr.get('motivo', '')}). "
                    f"1R = {rr.get('rischio_pct_prezzo', '?')}% del prezzo: per rischiare l'1% del capitale, posizione pari al {round(100 / rr['rischio_pct_prezzo'], 1) if rr.get('rischio_pct_prezzo') else '?'}% del capitale.\n"
                    f"Checklist ripartenza: {sum(1 for v in ck.values() if v)}/{len(ck)}.\n"
                    f"Solo misura statistica, non un ordine.")
    json.dump(sent[-500:], open(sent_p, 'w'), indent=0)


if __name__ == '__main__':
    main()
