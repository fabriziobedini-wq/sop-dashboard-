#!/usr/bin/env python3
"""
SOP Strategy Monitor v2 — GitHub Actions
Nuovo approccio: SOP = contesto | Price Action = entrata
Notifica solo quando ENTRAMBI sono allineati
"""

import os, json, time, math, requests
from datetime import datetime, timezone

TG_TOKEN = os.environ.get('TG_TOKEN', '')
TG_CHAT  = os.environ.get('TG_CHAT', '')
STATE_FILE = 'sop_state.json'
BINANCE_BASE = 'https://fapi.binance.com'
DASHBOARD_URL = 'https://fabriziobedini-wq.github.io/sop-dashboard-/'

# Whitelist fissa: top 10 crypto per MARKET CAP (non per volume/OI).
# Aggiorna manualmente ogni 1-3 mesi. Ultimo aggiornamento: 08/07/2026
# (fonte: CoinMarketCap, esclusi stablecoin)
ASSETS_FALLBACK = ['BTC','ETH','BNB','XRP','SOL','TRX','HYPE','DOGE','LEO','ZEC']

# ── TELEGRAM ──────────────────────────────────────────────────────────────
def send_tg(msg):
    if not TG_TOKEN or not TG_CHAT:
        print(f'[TG] {msg[:120]}')
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

def get_klines(sym, interval='4h', limit=100):
    data = bn_get('/fapi/v1/klines', {'symbol': f'{sym}USDT', 'interval': interval, 'limit': limit})
    if not data or not isinstance(data, list): return []
    return [{'o':float(k[1]),'h':float(k[2]),'l':float(k[3]),'c':float(k[4]),'v':float(k[5]),'t':int(k[0])} for k in data]

def get_klines_1h(sym, limit=50):
    return get_klines(sym, '1h', limit)

def get_ticker(sym):
    return bn_get('/fapi/v1/ticker/24hr', {'symbol': f'{sym}USDT'})

def get_funding(sym):
    data = bn_get('/fapi/v1/fundingRate', {'symbol': f'{sym}USDT', 'limit': 1})
    if data and isinstance(data, list) and len(data) > 0:
        return float(data[0].get('fundingRate', 0))
    return 0.0

def get_oi_history(sym):
    data = bn_get('/futures/data/openInterestHist', {'symbol': f'{sym}USDT', 'period': '4h', 'limit': 6})
    return data if isinstance(data, list) else []

def get_top_assets():
    """
    Universo tradabile: SOLO i top 10 per market cap (whitelist ASSETS_FALLBACK),
    filtrati sui simboli effettivamente disponibili come perpetual USDT su Binance.

    PRIMA (versione precedente): selezionava i top 15 per volume 24h su Binance
    con soglia minima di 20M$. Questo permetteva l'ingresso di altcoin a bassa
    capitalizzazione ma volume speculativo alto (es. LAB, TAIKO) — causa delle
    due perdite catastrofiche nel backtest (-65,52% e -34,32%): volume alto
    non equivale a liquidità profonda, e lo stop ATR-based veniva sfondato da
    gap improvvisi su questi asset.
    """
    tickers = bn_get('/fapi/v1/ticker/24hr')
    if not tickers or not isinstance(tickers, list):
        return ASSETS_FALLBACK.copy()
    if not isinstance(tickers[0], dict):
        return ASSETS_FALLBACK.copy()

    available = {
        t.get('symbol', '').replace('USDT', '')
        for t in tickers
        if isinstance(t, dict) and t.get('symbol', '').endswith('USDT')
    }

    final = [s for s in ASSETS_FALLBACK if s in available]
    return final if final else ASSETS_FALLBACK.copy()

# ── INDICATORS ────────────────────────────────────────────────────────────
def calc_ema(values, period):
    if len(values) < period: return None
    k = 2 / (period + 1)
    ema = sum(values[:period]) / period
    for v in values[period:]:
        ema = v * k + ema * (1 - k)
    return ema

def calc_atr(klines, period=14):
    if len(klines) < period + 1: return 0
    trs = []
    for i in range(1, len(klines)):
        h, l, pc = klines[i]['h'], klines[i]['l'], klines[i-1]['c']
        trs.append(max(h-l, abs(h-pc), abs(l-pc)))
    return sum(trs[-period:]) / period

def calc_cvd_dir(klines, lookback=12):
    recent = klines[-lookback:] if len(klines) >= lookback else klines
    cvd = sum(k['v'] if k['c'] >= k['o'] else -k['v'] for k in recent)
    return 'up' if cvd > 0 else 'down' if cvd < 0 else 'flat'

def calc_support_resistance(klines, lookback=30):
    """Find key S/R levels from recent highs and lows"""
    if len(klines) < lookback: return []
    recent = klines[-lookback:]
    highs = [k['h'] for k in recent]
    lows  = [k['l'] for k in recent]
    levels = []
    # Swing highs
    for i in range(2, len(recent)-2):
        if recent[i]['h'] > recent[i-1]['h'] and recent[i]['h'] > recent[i-2]['h'] and \
           recent[i]['h'] > recent[i+1]['h'] and recent[i]['h'] > recent[i+2]['h']:
            levels.append(('R', recent[i]['h']))
    # Swing lows
    for i in range(2, len(recent)-2):
        if recent[i]['l'] < recent[i-1]['l'] and recent[i]['l'] < recent[i-2]['l'] and \
           recent[i]['l'] < recent[i+1]['l'] and recent[i]['l'] < recent[i+2]['l']:
            levels.append(('S', recent[i]['l']))
    return levels

def nearest_level(price, levels, atr, direction):
    """Find if price is near a S/R level in the right direction"""
    threshold = atr * 0.5
    if direction == 'long':
        supports = [v for t,v in levels if t == 'S' and abs(price - v) < threshold]
        return min(supports, key=lambda v: abs(price-v)) if supports else None
    else:
        resistances = [v for t,v in levels if t == 'R' and abs(price - v) < threshold]
        return min(resistances, key=lambda v: abs(price-v)) if resistances else None

# ── PRICE ACTION PATTERNS ─────────────────────────────────────────────────
def detect_pin_bar(klines, direction):
    """
    Pin bar = strong rejection candle
    Long pin bar (bullish): long lower shadow, small body, little upper shadow
    Short pin bar (bearish): long upper shadow, small body, little lower shadow
    """
    if len(klines) < 3: return None
    k = klines[-2]  # Use completed candle, not current
    body = abs(k['c'] - k['o'])
    total_range = k['h'] - k['l']
    if total_range == 0: return None

    upper_shadow = k['h'] - max(k['c'], k['o'])
    lower_shadow = min(k['c'], k['o']) - k['l']
    body_ratio = body / total_range

    if direction == 'long':
        # Bullish pin: lower shadow >= 2x body, body in upper 40%
        if lower_shadow >= body * 2 and body_ratio < 0.35 and upper_shadow < lower_shadow * 0.5:
            return {'pattern': 'Pin Bar Bullish', 'strength': 'forte' if lower_shadow >= body * 3 else 'moderata'}
    else:
        # Bearish pin: upper shadow >= 2x body, body in lower 40%
        if upper_shadow >= body * 2 and body_ratio < 0.35 and lower_shadow < upper_shadow * 0.5:
            return {'pattern': 'Pin Bar Bearish', 'strength': 'forte' if upper_shadow >= body * 3 else 'moderata'}
    return None

def detect_engulfing(klines, direction):
    """
    Engulfing = candle that completely engulfs previous candle body
    """
    if len(klines) < 3: return None
    prev = klines[-3]
    curr = klines[-2]

    prev_body_top = max(prev['c'], prev['o'])
    prev_body_bot = min(prev['c'], prev['o'])
    curr_body_top = max(curr['c'], curr['o'])
    curr_body_bot = min(curr['c'], curr['o'])

    if direction == 'long':
        # Bullish engulfing: prev bearish, curr bullish and engulfs prev
        if prev['c'] < prev['o'] and curr['c'] > curr['o']:
            if curr_body_bot < prev_body_bot and curr_body_top > prev_body_top:
                vol_ratio = curr['v'] / prev['v'] if prev['v'] > 0 else 1
                return {'pattern': 'Engulfing Bullish', 'strength': 'forte' if vol_ratio > 1.5 else 'moderata'}
    else:
        # Bearish engulfing: prev bullish, curr bearish and engulfs prev
        if prev['c'] > prev['o'] and curr['c'] < curr['o']:
            if curr_body_top > prev_body_top and curr_body_bot < prev_body_bot:
                vol_ratio = curr['v'] / prev['v'] if prev['v'] > 0 else 1
                return {'pattern': 'Engulfing Bearish', 'strength': 'forte' if vol_ratio > 1.5 else 'moderata'}
    return None

def detect_ema_bounce(klines_4h, direction):
    """
    EMA20 or EMA50 bounce on 4h chart
    Price touched EMA and reversed
    """
    if len(klines_4h) < 60: return None
    closes = [k['c'] for k in klines_4h]
    lows   = [k['l'] for k in klines_4h]
    highs  = [k['h'] for k in klines_4h]

    ema20 = calc_ema(closes, 20)
    ema50 = calc_ema(closes, 50)
    if not ema20 or not ema50: return None

    price = closes[-2]  # completed candle
    atr = calc_atr(klines_4h)
    tolerance = atr * 0.3

    if direction == 'long':
        # Price bounced off EMA20 or EMA50 from below
        prev_low = lows[-2]
        if abs(prev_low - ema20) < tolerance and closes[-2] > ema20:
            return {'pattern': 'Bounce EMA20', 'level': round(ema20, 4), 'strength': 'forte'}
        if abs(prev_low - ema50) < tolerance and closes[-2] > ema50:
            return {'pattern': 'Bounce EMA50', 'level': round(ema50, 4), 'strength': 'forte'}
    else:
        # Price rejected EMA20 or EMA50 from above
        prev_high = highs[-2]
        if abs(prev_high - ema20) < tolerance and closes[-2] < ema20:
            return {'pattern': 'Rejection EMA20', 'level': round(ema20, 4), 'strength': 'forte'}
        if abs(prev_high - ema50) < tolerance and closes[-2] < ema50:
            return {'pattern': 'Rejection EMA50', 'level': round(ema50, 4), 'strength': 'forte'}
    return None

def detect_volume_spike(klines, lookback=20):
    """Volume significantly above average = confirmation"""
    if len(klines) < lookback + 1: return False
    avg_vol = sum(k['v'] for k in klines[-lookback-1:-1]) / lookback
    last_vol = klines[-2]['v']
    return last_vol > avg_vol * 1.5

# ── SOP CONTEXT ───────────────────────────────────────────────────────────
def calc_sop_context(sym):
    """Returns SOP macro context: bullish/bearish/neutral + strength"""
    klines = get_klines(sym)
    ticker = get_ticker(sym)
    if not klines or not ticker: return None

    fr_val = get_funding(sym)
    oi_hist = get_oi_history(sym)

    oi_delta = 0
    oi_current = 0
    if len(oi_hist) >= 2:
        try:
            oi_new = float(oi_hist[-1]['sumOpenInterestValue'])
            oi_old = float(oi_hist[0]['sumOpenInterestValue'])
            oi_current = oi_new
            oi_delta = (oi_new - oi_old) / oi_old * 100 if oi_old > 0 else 0
        except: pass

    cvd_dir = calc_cvd_dir(klines)
    price = float(ticker['lastPrice'])
    vol24h = float(ticker.get('quoteVolume', 0))

    # OI/Vol ratio for regime
    oi_vol_ratio = (oi_current / (vol24h / 24)) if vol24h > 0 else 0
    regime = 'structural' if oi_vol_ratio >= 3 else 'momentum' if oi_vol_ratio < 1 else 'mixed'

    # Bias
    oi_up = oi_delta > 1
    oi_dn = oi_delta < -1
    fr_pos = fr_val > 0.05
    fr_neg = fr_val < -0.005
    cvd_up = cvd_dir == 'up'
    cvd_dn = cvd_dir == 'down'

    if (oi_dn and fr_neg and cvd_up) or (oi_up and fr_neg and cvd_up) or (oi_dn and fr_pos and cvd_up):
        bias = 'long'
    elif (oi_up and fr_pos and not cvd_up) or (oi_up and not fr_pos and cvd_dn) or (oi_dn and fr_neg and cvd_dn):
        bias = 'short'
    else:
        bias = 'wait'

    # Solidity (simplified)
    score = 0
    if abs(oi_delta) > 3: score += 2
    elif abs(oi_delta) > 1: score += 1
    if cvd_up and bias == 'long': score += 2
    if cvd_dn and bias == 'short': score += 2
    if fr_pos and bias == 'short': score += 1
    if fr_neg and bias == 'long': score += 1
    solidity = 'solido' if score >= 4 else 'moderato' if score >= 2 else 'fragile'

    return {
        'sym': sym, 'price': price, 'bias': bias,
        'oi_delta': oi_delta, 'fr_val': fr_val,
        'cvd_dir': cvd_dir, 'regime': regime,
        'solidity': solidity, 'score': score,
        'oi_vol_ratio': round(oi_vol_ratio, 1),
    }

def calc_macro_context(assets):
    """Overall market direction based on BTC + majority"""
    btc = next((a for a in assets if a['sym'] == 'BTC'), None)
    if not btc: return 'neutral'

    longs = sum(1 for a in assets if a['bias'] == 'long')
    shorts = sum(1 for a in assets if a['bias'] == 'short')
    total = len(assets)

    if btc['bias'] == 'short' and shorts >= total * 0.6: return 'bearish'
    if btc['bias'] == 'long' and longs >= total * 0.5: return 'bullish'
    if btc['bias'] == 'long': return 'bullish'
    return 'neutral'

# ── ENTRY CALCULATION ─────────────────────────────────────────────────────
def calc_entry_levels(price, atr, direction, pattern_level=None):
    """Calculate precise entry, stop, TP based on ATR and pattern"""
    mult = 1.5  # standard
    if direction == 'long':
        entry = price  # enter at market on pattern confirmation
        stop = round(entry - max(atr * mult, entry * 0.015), 6)
        tp1  = round(entry + abs(entry - stop) * 2.5, 6)
        tp2  = round(entry + abs(entry - stop) * 4.0, 6)
    else:
        entry = price
        stop = round(entry + max(atr * mult, entry * 0.015), 6)
        tp1  = round(entry - abs(stop - entry) * 2.5, 6)
        tp2  = round(entry - abs(stop - entry) * 4.0, 6)

    rr = round(abs(tp1 - entry) / abs(stop - entry), 1)
    stop_pct = round(abs(stop - entry) / entry * 100, 2)

    return {'entry': entry, 'stop': stop, 'tp1': tp1, 'tp2': tp2, 'rr': rr, 'stop_pct': stop_pct}

# ── SIGNAL DETECTION ──────────────────────────────────────────────────────
def find_signal(sop, macro):
    """
    Main signal logic:
    1. SOP context must allow the direction
    2. Price action pattern must be present on 4h or 1h
    3. Signal must be NEW (not already sent)
    """
    sym = sop['sym']
    bias = sop['bias']
    if bias == 'wait': return None

    # Macro filter for crypto
    if macro == 'bearish' and bias == 'long': return None
    if macro == 'neutral' and bias == 'long' and sop['solidity'] != 'solido': return None
    if sop['solidity'] == 'fragile': return None
    if sop['regime'] == 'momentum' and sop['score'] < 4: return None

    price = sop['price']
    direction = bias

    # Get klines for pattern detection
    klines_4h = get_klines(sym, '4h', 100)
    klines_1h = get_klines_1h(sym, 60)
    if not klines_4h: return None

    atr_4h = calc_atr(klines_4h)
    levels = calc_support_resistance(klines_4h)
    vol_spike = detect_volume_spike(klines_4h)

    # Detect patterns — 4h first (stronger), then 1h
    pattern = None
    timeframe = None

    # 4h patterns
    p = detect_pin_bar(klines_4h, direction)
    if p: pattern, timeframe = p, '4h'
    if not pattern:
        p = detect_engulfing(klines_4h, direction)
        if p: pattern, timeframe = p, '4h'
    if not pattern:
        p = detect_ema_bounce(klines_4h, direction)
        if p: pattern, timeframe = p, '4h'

    # 1h patterns (if no 4h signal)
    if not pattern and klines_1h:
        p = detect_pin_bar(klines_1h, direction)
        if p: pattern, timeframe = p, '1h'
        if not pattern:
            p = detect_engulfing(klines_1h, direction)
            if p: pattern, timeframe = p, '1h'

    if not pattern: return None

    # Check if near a key level
    key_level = nearest_level(price, levels, atr_4h, direction)

    # Calculate entry
    levels_data = calc_entry_levels(price, atr_4h, direction)

    return {
        'sym': sym, 'direction': direction, 'price': price,
        'pattern': pattern['pattern'], 'pattern_strength': pattern['strength'],
        'timeframe': timeframe, 'key_level': key_level,
        'vol_spike': vol_spike, 'sop': sop, 'macro': macro,
        **levels_data
    }

# ── FORMAT SIGNAL ─────────────────────────────────────────────────────────
def format_signal(sig):
    emoji = '🟢' if sig['direction'] == 'long' else '🔴'
    dir_label = 'LONG' if sig['direction'] == 'long' else 'SHORT'

    # Rating
    score = 0
    if sig['sop']['solidity'] == 'solido': score += 2
    elif sig['sop']['solidity'] == 'moderato': score += 1
    if sig['pattern_strength'] == 'forte': score += 2
    elif sig['pattern_strength'] == 'moderata': score += 1
    if sig['key_level']: score += 1
    if sig['vol_spike']: score += 1
    if sig['sop']['regime'] == 'structural': score += 1

    rating = '⭐⭐⭐⭐⭐' if score >= 7 else '⭐⭐⭐⭐' if score >= 5 else '⭐⭐⭐' if score >= 3 else '⭐⭐'

    macro_label = {'bullish': '🟢 Bullish', 'bearish': '🔴 Bearish', 'neutral': '🟡 Indeciso'}[sig['macro']]
    regime_label = {'structural': '🏗️ Strutturale', 'mixed': '⚖️ Misto', 'momentum': '⚡ Momentum'}[sig['sop']['regime']]

    level_line = f"📍 Livello chiave: {sig['key_level']:.4g}" if sig['key_level'] else "📍 Nessun livello chiave vicino"
    vol_line = "📊 Volume: ✅ spike confermato" if sig['vol_spike'] else "📊 Volume: normale"

    msg = (
        f"{emoji} <b>{sig['sym']}</b> — {dir_label} | Rating: {rating}\n\n"
        f"🕯 Pattern: <b>{sig['pattern']}</b> ({sig['pattern_strength']}) su {sig['timeframe']}\n"
        f"{level_line}\n"
        f"{vol_line}\n\n"
        f"📈 <b>Contesto SOP:</b>\n"
        f"  Bias: {sig['sop']['bias'].upper()} | Solidità: {sig['sop']['solidity'].title()}\n"
        f"  Regime: {regime_label}\n"
        f"  OI delta: {sig['sop']['oi_delta']:+.1f}% | Funding: {sig['sop']['fr_val']:.4f}%\n"
        f"  Macro mercato: {macro_label}\n\n"
        f"💰 <b>Livelli operativi:</b>\n"
        f"  Entry: <b>{sig['entry']}</b>\n"
        f"  Stop: {sig['stop']} (−{sig['stop_pct']}%)\n"
        f"  TP1: {sig['tp1']} (R/R {sig['rr']}:1)\n"
        f"  TP2: {sig['tp2']}\n\n"
        f"🌐 <a href='{DASHBOARD_URL}'>Dashboard</a>"
    )
    return msg, score

# ── STATE ─────────────────────────────────────────────────────────────────
def load_state():
    try:
        with open(STATE_FILE) as f: return json.load(f)
    except: return {}

def save_state(state):
    with open(STATE_FILE, 'w') as f: json.dump(state, f, indent=2)

def signal_key(sig):
    """Unique key to avoid duplicate notifications"""
    price_rounded = round(sig['price'] / sig['entry'] * 100)
    return f"{sig['sym']}_{sig['direction']}_{sig['pattern']}_{sig['timeframe']}_{price_rounded}"

# ── MAIN ──────────────────────────────────────────────────────────────────
def run():
    now = datetime.now(timezone.utc).strftime('%H:%M UTC')
    print(f'[{now}] SOP v2 Monitor starting...')

    state = load_state()
    sent_signals = state.get('sent_signals', {})
    # Clean old signals (older than 4h)
    cutoff = time.time() - 4 * 3600
    sent_signals = {k: v for k, v in sent_signals.items() if v > cutoff}

    assets_list = get_top_assets()
    print(f'Assets: {assets_list}')

    # Step 1: compute SOP context for all assets
    all_sop = []
    for sym in assets_list:
        try:
            ctx = calc_sop_context(sym)
            if ctx:
                all_sop.append(ctx)
                print(f'  {sym}: bias={ctx["bias"]} solidity={ctx["solidity"]} regime={ctx["regime"]}')
            time.sleep(0.4)
        except Exception as e:
            print(f'  {sym}: ERROR {e}')

    if not all_sop:
        print('No SOP data — abort')
        save_state({**state, 'sent_signals': sent_signals})
        return

    # Step 2: macro context
    macro = calc_macro_context(all_sop)
    print(f'Macro: {macro}')

    # Step 3: find price action signals
    signals_found = []
    for sop in all_sop:
        try:
            sig = find_signal(sop, macro)
            if sig:
                key = signal_key(sig)
                if key not in sent_signals:
                    signals_found.append((sig, key))
                    print(f'  ✅ SIGNAL: {sig["sym"]} {sig["direction"]} {sig["pattern"]} {sig["timeframe"]}')
                else:
                    print(f'  ⏭ Already sent: {sig["sym"]} {sig["direction"]}')
            time.sleep(0.3)
        except Exception as e:
            print(f'  {sop["sym"]}: signal error {e}')

    # Step 4: send notifications (sorted by score, best first)
    signals_found.sort(key=lambda x: format_signal(x[0])[1], reverse=True)

    for sig, key in signals_found:
        msg, score = format_signal(sig)
        print(f'Sending: {sig["sym"]} {sig["direction"]} score={score}')
        send_tg(msg)
        sent_signals[key] = time.time()
        time.sleep(1)

    if not signals_found:
        print('No new signals this run')

    # Update state
    state['sent_signals'] = sent_signals
    state['last_run'] = now
    state['macro'] = macro
    save_state(state)
    print(f'Done. {len(signals_found)} signals sent.')

if __name__ == '__main__':
    run()

