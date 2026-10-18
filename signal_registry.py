#!/usr/bin/env python3
"""
Registro dei segnali consigliati dal monitor, anche quelli che Fabrizio NON apre.

Ogni segnale che il backend notifica viene salvato in signals_log.json con
entry/stop/TP come comunicati. Ad ogni giro (ogni 15 min) i segnali ancora
aperti vengono "giocati su carta" sulle candele 15m (OKX) dopo la notifica,
con le STESSE regole del dashboard:
  - stop iniziale; a 45% del percorso verso TP1 lo stop va a pareggio
  - TP1 raggiunto -> stop a pareggio (il trade continua)
  - TP2 raggiunto -> chiuso a TP2
  - stop colpito -> chiuso allo stop (o a pareggio se già spostato)
  - nessuna chiusura entro EXPIRE_HOURS -> chiuso al prezzo di mercato ("scaduto")
Regola prudente: se nella stessa candela 15m sono toccati sia lo stop sia un
target, si assume che lo stop sia stato colpito prima. Le chiusure per
"bias invertito" e "manuale" del dashboard NON sono simulabili.

Solo simulazione: nessun ordine, nessun broker.
"""
import json
import os

SIGNALS_FILE = 'signals_log.json'
BE_TRIGGER = 0.45        # % del percorso verso TP1 per spostare lo stop a pareggio
EXPIRE_HOURS = 240       # 10 giorni
BAR_MS = 15 * 60 * 1000


def load_signals(path=SIGNALS_FILE):
    try:
        with open(path) as f:
            data = json.load(f)
            return data if isinstance(data, list) else []
    except Exception:
        return []


def save_signals(signals, path=SIGNALS_FILE):
    tmp = path + '.tmp'
    with open(tmp, 'w') as f:
        json.dump(signals, f, indent=1, ensure_ascii=False)
    os.replace(tmp, path)


def log_signal(signals, sig, score, now_ms):
    """Aggiunge il segnale al registro. Ritorna True se aggiunto.
    Non duplica: se per lo stesso asset+direzione c'è già un segnale ancora aperto, salta."""
    for s in signals:
        if (s['sym'] == sig['sym'] and s['dir'] == sig['direction'] and s['status'] == 'open'
                and s.get('vetoed') == sig.get('vetoed')):
            return False
    sop = sig.get('sop') or {}
    signals.append({
        'id': now_ms,
        'sym': sig['sym'],
        'dir': sig['direction'],
        'createdAt': now_ms,
        'entry': sig['entry'],
        'stop': sig['stop'],
        'stopInitial': sig['stop'],
        'tp1': sig['tp1'],
        'tp2': sig['tp2'],
        'rr': sig.get('rr'),
        'stopPct': sig.get('stop_pct'),
        'pattern': sig.get('pattern'),
        'patternStrength': sig.get('pattern_strength'),
        'timeframe': sig.get('timeframe'),
        'score': score,
        'macro': sig.get('macro'),
        'bias': sop.get('bias'),
        'solidity': sop.get('solidity'),
        'regime': sop.get('regime'),
        'vetoed': sig.get('vetoed'),
        'status': 'open',
        'tp1Hit': False,
        'breakevenSet': False,
        'checkedUntil': now_ms,
    })
    return True


def _pnl(s, price):
    sign = 1 if s['dir'] == 'long' else -1
    return round(sign * (price - s['entry']) / s['entry'] * 100, 2)


def simulate(s, bars, now_ms):
    """Applica le candele 15m (ordinate, con chiave t=apertura ms) a un segnale aperto.
    Modifica s in place. Considera solo candele aperte DOPO la notifica (candela successiva)."""
    is_long = s['dir'] == 'long'
    entry, tp1, tp2 = s['entry'], s['tp1'], s['tp2']
    stop = s['stop']
    first_ok = s['createdAt']  # una candela già in corso alla notifica non si usa
    start = max(s['checkedUntil'], first_ok)
    last = None
    for b in bars:
        t = b['t']
        if t < start or t < first_ok:
            continue
        # la candela deve essere chiusa
        if t + BAR_MS > now_ms:
            break
        last = b
        s['checkedUntil'] = t + BAR_MS
        hit_stop = b['l'] <= stop if is_long else b['h'] >= stop
        if hit_stop:
            _close(s, stop, t, 'breakeven' if abs(stop - entry) < 1e-12 else 'stop')
            return s
        hit_tp2 = b['h'] >= tp2 if is_long else b['l'] <= tp2
        hit_tp1 = b['h'] >= tp1 if is_long else b['l'] <= tp1
        if hit_tp2:
            s['tp1Hit'] = True
            _close(s, tp2, t, 'tp2')
            return s
        if hit_tp1 and not s['tp1Hit']:
            s['tp1Hit'] = True
            s['tp1HitAt'] = t
            stop = entry
            s['stop'] = stop
            s['breakevenSet'] = True
        if not s['breakevenSet'] and not s['tp1Hit']:
            dist = abs(tp1 - entry)
            reached = (b['h'] - entry) if is_long else (entry - b['l'])
            if dist > 0 and reached / dist >= BE_TRIGGER:
                stop = entry
                s['stop'] = stop
                s['breakevenSet'] = True
    # scadenza
    if s['status'] == 'open' and now_ms - s['createdAt'] >= EXPIRE_HOURS * 3600 * 1000 and last:
        _close(s, last['c'], last['t'] + BAR_MS, 'expired')
    return s


def _close(s, price, t_ms, reason):
    s['status'] = 'closed'
    s['closeReason'] = reason
    s['closedAt'] = t_ms
    s['closePrice'] = price
    s['pnlPct'] = _pnl(s, price)


def update_open_signals(signals, fetch_bars, now_ms):
    """fetch_bars(sym) -> lista candele 15m [{t,o,h,l,c}] ordinate. Ritorna n. di segnali chiusi."""
    closed = 0
    for s in signals:
        if s['status'] != 'open':
            continue
        try:
            bars = fetch_bars(s['sym'])
        except Exception as e:
            print(f"  registro {s['sym']}: errore dati {e}")
            continue
        if not bars:
            continue
        simulate(s, bars, now_ms)
        if s['status'] == 'closed':
            closed += 1
    return closed


# ── Stato del mercato nel tempo ───────────────────────────────────────────
STATE_LOG = 'state_log.jsonl'


def log_state(all_sop, macro, path=STATE_LOG, now_ms=None):
    """Aggiunge una riga a state_log.jsonl con macro e (bias, solidità, regime) di ogni asset,
    ma solo se è cambiato qualcosa rispetto all'ultima riga. Serve a rispondere, coi dati,
    a domande come 'il mercato è sempre indeciso?'."""
    import time as _t
    snap = {'macro': macro,
            'assets': {c['sym']: [c.get('bias'), c.get('solidity'), c.get('regime')] for c in all_sop}}
    last = None
    try:
        with open(path) as f:
            for line in f:
                if line.strip():
                    last = json.loads(line)
    except Exception:
        last = None
    if last and last.get('macro') == snap['macro'] and last.get('assets') == snap['assets']:
        return False
    snap['t'] = now_ms or int(_t.time() * 1000)
    with open(path, 'a') as f:
        f.write(json.dumps(snap, ensure_ascii=False) + '\n')
    return True


# ── Controllo dei trade aperti nel dashboard (anche a pagina chiusa) ──────
CHECKS_FILE = 'trade_checks.json'


def load_checks(path=CHECKS_FILE):
    try:
        with open(path) as f:
            d = json.load(f)
            return d if isinstance(d, dict) else {}
    except Exception:
        return {}


def save_checks(checks, path=CHECKS_FILE):
    tmp = path + '.tmp'
    with open(tmp, 'w') as f:
        json.dump(checks, f, indent=1, ensure_ascii=False, sort_keys=True)
    os.replace(tmp, path)


def check_trades(trades, checks, fetch_bars, now_ms):
    """Per ogni trade attivo del dashboard (open_trades.json) rigioca le candele 15m dall'attivazione
    con le stesse regole del registro. Scrive l'esito in `checks` (chiave = id del trade), SENZA
    toccare open_trades.json (che il sync copia dal browser).
    Prudenza: se il trade ha già lo stop a pareggio (breakevenSet/tp1Hit) e non conosco il momento
    (tp1HitAt), non so quale fosse lo stop originale -> controllo solo da ora in avanti.
    Ritorna la lista dei trade chiusi in questo giro."""
    newly_closed = []
    for t in trades:
        if t.get('closed') or t.get('pending') or t.get('neverEntered'):
            continue
        tid = str(t.get('id'))
        if not tid or t.get('entry') is None or t.get('stop') is None or not t.get('tp1') or not t.get('tp2'):
            continue
        s = checks.get(tid)
        if s is None:
            act = t.get('activatedAt') or t.get('openedAt') or now_ms
            be_known = bool(t.get('breakevenSet') or t.get('tp1Hit'))
            if be_known and t.get('tp1HitAt'):
                start, stop, mode = t['tp1HitAt'], t['entry'], 'da TP1'
            elif be_known:
                start, stop, mode = now_ms, t['stop'], 'solo da ora (stop già spostato, momento ignoto)'
            else:
                start, stop, mode = act, t['stop'], 'da attivazione'
            s = {'id': t['id'], 'sym': t['sym'], 'dir': t['dir'], 'entry': t['entry'], 'stop': stop,
                 'stopInitial': t['stop'], 'tp1': t['tp1'], 'tp2': t['tp2'], 'createdAt': start,
                 'checkedUntil': start, 'tp1Hit': bool(t.get('tp1Hit')),
                 'breakevenSet': bool(t.get('breakevenSet')), 'status': 'open', 'mode': mode}
            checks[tid] = s
        if s.get('status') != 'open':
            continue
        try:
            bars = fetch_bars(s['sym'])
        except Exception as e:
            print(f"  controllo trade {s['sym']}: errore dati {e}")
            continue
        if not bars:
            continue
        simulate(s, bars, now_ms)
        s['lastCheck'] = now_ms
        if s['status'] == 'closed':
            newly_closed.append(s)
    return newly_closed
