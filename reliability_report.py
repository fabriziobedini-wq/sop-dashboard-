#!/usr/bin/env python3
"""
Report di affidabilità del SOP Strategy Monitor, calcolato da open_trades.json.
Uso:  python3 reliability_report.py            -> stampa il report
      python3 reliability_report.py --write    -> scrive anche RELIABILITY.md

Considera solo i trade chiusi e realmente attivati (pnlPct presente).
I trade 'pending' mai attivati (entry mai raggiunta) sono contati a parte.
Il campo `context` (macro, solidity, regime, phase...) esiste solo sui trade
aperti dopo l'introduzione della registrazione del contesto: finché il campione
è piccolo le tabelle per contesto sono INDICATIVE, non conclusive.
"""
import json, sys
from collections import defaultdict
from datetime import datetime, timezone

TRADES_FILE = 'open_trades.json'
MIN_N = 10  # sotto questa numerosità un bucket è solo aneddotico
# Il 'nuovo percorso' (stop controllati con TradingView, veto MA20, fix price action,
# sync automatica) parte da ottobre 2026: il giudizio sul sistema si fa da qui.
BASELINE = datetime(2026, 10, 1, tzinfo=timezone.utc)
BASELINE_MS = int(BASELINE.timestamp() * 1000)


def load():
    with open(TRADES_FILE) as f:
        return json.load(f)


def stats(rows):
    n = len(rows)
    if not n:
        return dict(n=0, wr=0.0, tot=0.0, avg=0.0, avg_w=0.0, avg_l=0.0)
    p = [t['pnlPct'] for t in rows]
    w = [x for x in p if x > 0]
    l = [x for x in p if x <= 0]
    return dict(n=n, wr=100 * len(w) / n, tot=sum(p), avg=sum(p) / n,
                avg_w=sum(w) / len(w) if w else 0.0,
                avg_l=sum(l) / len(l) if l else 0.0)


def fmt(s):
    flag = '' if s['n'] >= MIN_N else ' (campione piccolo)'
    return (f"n={s['n']:>3}  WR={s['wr']:5.1f}%  pnl tot={s['tot']:+7.2f}%  "
            f"medio={s['avg']:+5.2f}%  win medio={s['avg_w']:+5.2f}%  "
            f"loss medio={s['avg_l']:+6.2f}%{flag}")


def group(rows, keyf):
    g = defaultdict(list)
    for t in rows:
        g[keyf(t)].append(t)
    return g


def section(title, g, lines, order=None):
    lines.append(f"\n### {title}")
    keys = order or sorted(g, key=lambda k: -len(g[k]))
    for k in keys:
        if k in g:
            lines.append(f"- **{k}**: {fmt(stats(g[k]))}")


def build():
    trades = load()
    done = [t for t in trades if t.get('closed') and not t.get('pending')
            and t.get('pnlPct') is not None]
    done.sort(key=lambda t: t.get('closedAt') or t['id'])
    never_filled = [t for t in trades if t.get('pending') and t.get('closed')]
    open_now = [t for t in trades if not t.get('closed') and not t.get('pending')]
    waiting = [t for t in trades if not t.get('closed') and t.get('pending')]

    L = []
    now = datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')
    L.append(f"# Report affidabilità SOP — {now}")
    L.append(f"\nTrade chiusi attivati: **{len(done)}** · mai attivati (entry non raggiunta): "
             f"{len(never_filled)} · aperti ora: {len(open_now)} · in attesa: {len(waiting)}")

    new = [t for t in done if (t.get('closedAt') or 0) >= BASELINE_MS]
    L.append("\n## NUOVO PERCORSO — dal 1 ottobre 2026 (il numero che conta)")
    L.append(f"- {fmt(stats(new))}")
    if len(new) < 30:
        L.append(f"- Servono ~30 trade chiusi per un giudizio: ne mancano {30 - len(new)}.")
    for t in new:
        d = datetime.fromtimestamp(t['closedAt'] / 1000, timezone.utc).strftime('%d/%m')
        L.append(f"  - {d} {t['sym']} {t['dir']}: {t['pnlPct']:+.2f}% ({t.get('closeReason') or '?'})")

    L.append("\n## Storico completo (include il periodo prima del nuovo percorso)")
    L.append(f"- Tutti: {fmt(stats(done))}")

    # stop sfondati: perdita molto oltre la distanza dello stop teorica
    blown = []
    for t in done:
        if t.get('closeReason') == 'stop' and t.get('entry') and t.get('stop'):
            theo = abs(t['stop'] - t['entry']) / t['entry'] * 100
            if theo < 0.5:   # stop a breakeven/trailing: non è una perdita da stop sfondato
                continue
            if t['pnlPct'] < -(theo * 1.5 + 0.5):
                blown.append((t, theo))
    ok = [t for t in done if t not in [b[0] for b in blown]]
    L.append(f"- Senza stop sfondati ({len(blown)} esclusi): {fmt(stats(ok))}")
    if blown:
        L.append("\n  Stop sfondati (perdita > 1.5x la distanza teorica dello stop):")
        for t, theo in blown:
            L.append(f"  - {t['sym']} {t['dir']}: stop teorico -{theo:.2f}% → chiuso {t['pnlPct']:+.2f}%")

    # tendenza: ultimi 20 vs precedenti
    if len(done) >= 30:
        a, b = done[:-20], done[-20:]
        L.append(f"\n## Tendenza (ordine di chiusura)")
        L.append(f"- Precedenti ({len(a)}): {fmt(stats(a))}")
        L.append(f"- Ultimi 20:  {fmt(stats(b))}")

    section("Per direzione", group(done, lambda t: t['dir']), L)
    section("Per asset", group(done, lambda t: t['sym']), L)
    section("Per motivo di chiusura", group(done, lambda t: t.get('closeReason') or '?'), L)
    section("TP1 raggiunto?", group(done, lambda t: 'sì' if t.get('tp1Hit') else 'no'), L)

    ctx = [t for t in done if t.get('context')]
    L.append(f"\n## Per contesto all'apertura (solo {len(ctx)} trade con contesto registrato)")
    if ctx:
        section("Macro", group(ctx, lambda t: t['context'].get('macro')), L)
        section("Solidità", group(ctx, lambda t: t['context'].get('solidity')), L)
        section("Regime", group(ctx, lambda t: t['context'].get('regime')), L)
        section("Fase money-flow", group(ctx, lambda t: t['context'].get('phase')), L)
        section("Qualità zona", group(ctx, lambda t: t['context'].get('quality')), L)
    else:
        L.append("- nessun trade chiuso con contesto ancora")

    if open_now:
        L.append("\n## Aperti ora")
        for t in open_now:
            c = t.get('context') or {}
            L.append(f"- {t['sym']} {t['dir']} @ {t['entry']} · TP1 {'preso' if t.get('tp1Hit') else 'no'}"
                     f" · macro={c.get('macro','?')} solidità={c.get('solidity','?')} fase={c.get('phase','?')}")

    L.append("\n_Lettura: sotto n=10 un bucket è aneddotico. Un sistema si giudica su "
             "expectancy (pnl medio per trade) e sulla coda delle perdite, non sul win rate da solo._")
    return '\n'.join(L)


def append_history():
    """Aggiunge una riga a reliability_history.csv (solo se i numeri sono cambiati),
    per vedere nel tempo se expectancy e win rate migliorano o peggiorano."""
    import csv, os
    trades = load()
    done = sorted([t for t in trades if t.get('closed') and not t.get('pending')
                   and t.get('pnlPct') is not None],
                  key=lambda t: t.get('closedAt') or t['id'])
    s = stats(done)
    l20 = stats(done[-20:])
    row = [datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M'), s['n'],
           round(s['wr'], 1), round(s['tot'], 2), round(s['avg'], 2),
           round(l20['wr'], 1), round(l20['tot'], 2), round(l20['avg'], 2)]
    path = 'reliability_history.csv'
    new = not os.path.exists(path)
    last = None
    if not new:
        with open(path) as f:
            rows = list(csv.reader(f))
            last = rows[-1] if len(rows) > 1 else None
    if last and last[1:5] == [str(x) for x in row[1:5]]:
        return False
    with open(path, 'a', newline='') as f:
        w = csv.writer(f)
        if new:
            w.writerow(['utc', 'n_chiusi', 'wr_pct', 'pnl_tot_pct', 'expectancy_pct',
                        'wr_ultimi20', 'pnl_ultimi20', 'expectancy_ultimi20'])
        w.writerow(row)
    return True


if __name__ == '__main__':
    rep = build()
    print(rep)
    if '--write' in sys.argv:
        with open('RELIABILITY.md', 'w') as f:
            f.write(rep + '\n')
        append_history()
