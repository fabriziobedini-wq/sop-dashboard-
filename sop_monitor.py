#!/usr/bin/env python3
"""
SOP Strategy Monitor — GitHub Actions
Runs every 5 minutes, checks Binance signals, sends Telegram alerts
"""

import os, json, time, math, requests
from datetime import datetime, timezone

# ── CONFIG ────────────────────────────────────────────────────────────────
TG_TOKEN = os.environ.get('TG_TOKEN', '')
TG_CHAT  = os.environ.get('TG_CHAT', '')
STATE_FILE = 'sop_state.json'
BINANCE_BASE = 'https://fapi.binance.com'

# Top assets to monitor (fallback if dynamic load fails)
ASSETS_FALLBACK = ['BTC','ETH','SOL','BNB','XRP','DOGE','ADA','AVAX','LINK','DOT']

# ── TELEGRAM ──────────────────────────────────────────────────────────────
def send_tg(msg):
    if not TG_TOKEN or not TG_CHAT:
        print(f'[TG] {msg[:80]}')
        return
    try:
        requests.post(
            f'https://api.telegram.org/bot{TG_TOKEN}/sendMessage',
            json={'chat_id': TG_CHAT, 'text': msg, 'parse_mode': 'HTML'},
            timeout=10
        )
    except Exception as e:
        print(f'TG error: {e}')

# ── BINANCE API ───────────────────────────────────────────────────────────
def bn_get(path, params=None):
    try:
        r = requests.get(f'{BINANCE_BASE}{path}', params=params or {}, timeout=10)
        return r.json()
    except Exception as e:
        print(f'Binance error {path}: {e}')
        return None

def get_klines(sym, interval='4h', limit=48):
    data = bn_get('/fapi/v1/klines', {'symbol': f'{sym}USDT', 'interval': interval, 'limit': limit})
    if not data: return []
    return [{'o':float(k[1]),'h':float(k[2]),'l':float(k[3]),'c':float(k[4]),'v':float(k[5])} for k in data]

def get_ticker(sym):
    return bn_get('/fapi/v1/ticker/24hr', {'symbol': f'{sym}USDT'})

def get_funding(sym):
    data = bn_get('/fapi/v1/fundingRate', {'symbol': f'{sym}USDT', 'limit': 1})
    return float(data[0]['fundingRate']) if data else 0

def get_oi_history(sym):
    data = bn_get('/futures/data/openInterestHist', {'symbol': f'{sym}USDT', 'period': '4h', 'limit': 4})
    return data or []

def get_top_assets():
    tickers = bn_get('/fapi/v1/ticker/24hr')
    if not tickers or not isinstance(tickers, list): return ASSETS_FALLBACK
    # Make sure we have dicts, not strings
    if not isinstance(tickers[0], dict): return ASSETS_FALLBACK
    excluded = {'USDC','BUSD','TUSD','FDUSD','USDP','DAI','USDT','USDE',
                'UP','DOWN','BULL','BEAR','LONG','SHORT',
                'CL','XAU','XAG','SPX','NDX','SOXL','SPCX',
                'AAPL','TSLA','NVDA','AMZN','GOOGL','MSFT','META','COIN','MSTR'}
    usdt = [t for t in tickers if isinstance(t, dict) and t.get('symbol','').endswith('USDT')]
    filtered = []
    for t in usdt:
        sym = t['symbol'].replace('USDT','')
        vol = float(t.get('quoteVolume',0))
        price = float(t.get('lastPrice',0))
        if sym in excluded: continue
        if any(sym.startswith(e) for e in excluded): continue
        if price > 15000 and sym != 'BTC': continue
        if vol < 20000000: continue
        filtered.append({'sym': sym, 'vol': vol})
    if not filtered: return ASSETS_FALLBACK
    filtered.sort(key=lambda x: -x['vol'])
    top = [t['sym'] for t in filtered[:15]]
    macro = ['BTC','ETH','SOL']
    final = list(dict.fromkeys(macro + top))[:12]
    return final

# ── CALCULATIONS ──────────────────────────────────────────────────────────
def calc_atr(klines, period=14):
    if len(klines) < period + 1: return 0
    trs = []
    for i in range(1, len(klines)):
        h, l, pc = klines[i]['h'], klines[i]['l'], klines[i-1]['c']
        trs.append(max(h-l, abs(h-pc), abs(l-pc)))
    return sum(trs[-period:]) / period

def calc_cvd(klines):
    """Approximate CVD from candle direction and volume"""
    cvd = 0
    for k in klines:
        if k['c'] >= k['o']:  # bullish candle
            cvd += k['v']
        else:
            cvd -= k['v']
    # Direction based on last 12 candles
    recent = klines[-12:] if len(klines) >= 12 else klines
    recent_cvd = sum(k['v'] if k['c'] >= k['o'] else -k['v'] for k in recent)
    direction = 'up' if recent_cvd > 0 else 'down' if recent_cvd < 0 else 'flat'
    return {'total': cvd, 'dir': direction, 'recent': recent_cvd}

def calc_bias(oi_delta, fr_val, cvd_dir):
    """Core SOP bias matrix"""
    oi_up = oi_delta > 1
    oi_dn = oi_delta < -1
    fr_pos = fr_val > 0.05
    fr_neg = fr_val < -0.005
    fr_neu = not fr_pos and not fr_neg
    cvd_up = cvd_dir == 'up'
    cvd_dn = cvd_dir == 'down'

    # LONG conditions
    if oi_dn and (fr_neg or fr_neu) and cvd_up: return 'long'   # OI flush + CVD buy
    if oi_up and fr_neg and cvd_up: return 'long'                # leva long + funding neg
    if oi_dn and fr_pos and cvd_up: return 'long'               # short flush

    # SHORT conditions
    if oi_up and fr_pos and not cvd_up: return 'short'          # leva short excess
    if oi_up and fr_neu and cvd_dn: return 'short'              # build + sell pressure
    if oi_dn and fr_neg and cvd_dn: return 'short'              # long liquidation

    return 'wait'

def calc_quality(bias, oi_delta, fr_val, cvd_dir, oi_vol_ratio):
    if bias == 'wait': return 0
    score = 0
    if bias == 'long':
        if cvd_dir == 'up': score += 2
        if fr_val < 0: score += 1
        if oi_delta < -2: score += 1
    else:
        if cvd_dir == 'down': score += 2
        if fr_val > 0.03: score += 1
        if oi_delta > 2: score += 1
    if oi_vol_ratio and 1 < oi_vol_ratio < 4: score += 1
    return min(score, 5)

# ── STATE MANAGEMENT ──────────────────────────────────────────────────────
def load_state():
    try:
        with open(STATE_FILE) as f:
            return json.load(f)
    except:
        return {}

def save_state(state):
    with open(STATE_FILE, 'w') as f:
        json.dump(state, f, indent=2)

# ── MAIN MONITOR ──────────────────────────────────────────────────────────
def compute_signal(sym):
    klines = get_klines(sym)
    if not klines: return None

    ticker = get_ticker(sym)
    if not ticker: return None

    price = float(ticker['lastPrice'])
    vol24h = float(ticker['quoteVolume'])

    fr_val = get_funding(sym)
    oi_hist = get_oi_history(sym)

    oi_delta = 0
    oi_current = 0
    if len(oi_hist) >= 2:
        oi_new = float(oi_hist[-1]['sumOpenInterestValue'])
        oi_old = float(oi_hist[0]['sumOpenInterestValue'])
        oi_current = oi_new
        oi_delta = (oi_new - oi_old) / oi_old * 100 if oi_old > 0 else 0

    cvd = calc_cvd(klines)
    atr = calc_atr(klines)
    oi_vol_ratio = (oi_current / (vol24h / 24)) if vol24h > 0 else 0

    bias = calc_bias(oi_delta, fr_val, cvd['dir'])
    quality = calc_quality(bias, oi_delta, fr_val, cvd['dir'], oi_vol_ratio)

    return {
        'sym': sym, 'price': price, 'bias': bias,
        'quality': quality, 'oi_delta': oi_delta,
        'fr_val': fr_val, 'cvd_dir': cvd['dir'],
        'oi_vol_ratio': round(oi_vol_ratio, 2),
        'atr': atr, 'ts': int(time.time())
    }

def check_signal_changes(sym, current, prev_state):
    alerts = []
    if not prev_state: return alerts

    prev_bias = prev_state.get('bias', 'wait')
    prev_ts = prev_state.get('ts', 0)
    hours_since = (time.time() - prev_ts) / 3600

    # New strong signal (bias changed + quality >= 3)
    if (current['bias'] != prev_bias and
        current['bias'] != 'wait' and
        current['quality'] >= 3 and
        hours_since > 1):  # avoid spam
        stars = '★' * current['quality'] + '☆' * (5 - current['quality'])
        emoji = '🟢' if current['bias'] == 'long' else '🔴'
        alerts.append(
            f"{emoji} <b>{sym}</b> — NUOVO SEGNALE {current['bias'].upper()}\n"
            f"Bias cambiato da {prev_bias.upper()} → {current['bias'].upper()}\n"
            f"Qualità: {stars}\n"
            f"OI delta: {current['oi_delta']:+.1f}% | Funding: {current['fr_val']:.4f}%\n"
            f"CVD: {current['cvd_dir']} | OI/Vol: {current['oi_vol_ratio']}x\n"
            f"Prezzo: {current['price']}\n"
            f"🌐 https://fabriziobedini-wq.github.io/sop-dashboard-/"
        )

    # Quality degraded warning
    if (prev_state.get('quality', 0) >= 3 and
        current['quality'] < 3 and
        current['bias'] == prev_bias and
        current['bias'] != 'wait'):
        alerts.append(
            f"🟡 <b>{sym}</b> — Segnale indebolito\n"
            f"Bias {current['bias'].upper()} ancora attivo ma qualità scesa a {current['quality']}★\n"
            f"Prezzo: {current['price']}"
        )

    return alerts

def run():
    print(f'[{datetime.now(timezone.utc).strftime("%H:%M UTC")}] SOP Monitor starting...')

    assets = get_top_assets()
    print(f'Assets: {assets}')

    state = load_state()
    new_state = dict(state)  # preserve trade monitoring state

    all_alerts = []

    for sym in assets:
        try:
            sig = compute_signal(sym)
            if not sig:
                print(f'  {sym}: no data')
                continue

            prev = state.get(f'signal_{sym}')
            alerts = check_signal_changes(sym, sig, prev)
            all_alerts.extend(alerts)

            new_state[f'signal_{sym}'] = sig
            print(f'  {sym}: {sig["bias"].upper()} Q{sig["quality"]} OI{sig["oi_delta"]:+.1f}% FR{sig["fr_val"]:.4f}')

            time.sleep(0.3)  # rate limit
        except Exception as e:
            print(f'  {sym}: ERROR {e}')

    # Send alerts
    for alert in all_alerts:
        send_tg(alert)
        time.sleep(1)

    if not all_alerts:
        print('No new alerts')

    save_state(new_state)
    print(f'Done. {len(all_alerts)} alerts sent.')

if __name__ == '__main__':
    run()
