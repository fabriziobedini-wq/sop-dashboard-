#!/usr/bin/env python3
"""Unisce la scansione fatta nel cloud con il database del radar.
Uso: python3 merge.py DB_DIR OUT_DIR [status.json SOP] > plan.json
DB_DIR: export di ArtifactData (DB_DIR/proposals/*.json, DB_DIR/scans/latest.json)
OUT_DIR: radar_cloud/out del repo (scan_latest.json, candidates.json, bars_tail.json)
Stampa un piano JSON: proposte nuove da creare, proposte aperte da chiudere, scans/latest da scrivere.
Regole identiche alla pagina: niente doppioni (stesso asset e lato aperto o già proposto oggi),
massimo 3 posizioni aperte (Regole 2+) nello stesso gruppo e lato, valutazione con TP1 prima dello stop,
stessa candela = stop, scadenza dopo 30 candele."""
import glob, json, os, re, sys, time
ID_RE = re.compile(r'^[A-Za-z0-9_\-.~:@+]{1,200}$')

HZ, MAX_CLUSTER = 30, 3
db_dir, out_dir = sys.argv[1], sys.argv[2]
sop_path = sys.argv[3] if len(sys.argv) > 3 else None
load = lambda p: (lambda d: d.get('data', d) if isinstance(d, dict) else d)(json.load(open(p)))

props = {}
for f in glob.glob(os.path.join(db_dir, 'proposals', '*.json')):
    props[os.path.basename(f)[:-5]] = load(f)
db_scan = load(os.path.join(db_dir, 'scans', 'latest.json')) if os.path.exists(os.path.join(db_dir, 'scans', 'latest.json')) else {}
scan = load(os.path.join(out_dir, 'scan_latest.json'))
cands = json.load(open(os.path.join(out_dir, 'candidates.json')))
tail = json.load(open(os.path.join(out_dir, 'bars_tail.json')))
now = time.time() * 1000


def eval_p(p, bars):
    d = 1 if float(p['dir']) > 0 else -1
    e, st, t1 = float(p['entry']), float(p['stop']), float(p['tp1'])
    t2 = float(p['tp2']) if p.get('tp2') is not None else None
    risk = abs(e - st)
    if not risk:
        return None
    j = next((k for k, b in enumerate(bars) if b['t'] * 1000 >= float(p['ts'])), None)
    if j is None:
        return None
    r1 = abs(t1 - e) / risk; hit1 = False; hit1ts = None
    for k in range(j, min(len(bars), j + HZ)):
        b = bars[k]
        sh = b['l'] <= st if d > 0 else b['h'] >= st
        h1 = b['h'] >= t1 if d > 0 else b['l'] <= t1
        h2 = t2 is not None and (b['h'] >= t2 if d > 0 else b['l'] <= t2)
        if not hit1:
            if sh:
                return {'status': 'stop', 'R': -1, 'exit': st, 'closedTs': b['t'] * 1000}
            if h1:
                hit1 = True; hit1ts = b['t'] * 1000
                if h2:
                    return {'status': 'tp2', 'R': round(r1, 3), 'exit': t1, 'closedTs': b['t'] * 1000}
        else:
            if h2:
                return {'status': 'tp2', 'R': round(r1, 3), 'exit': t1, 'closedTs': b['t'] * 1000}
            if sh:
                return {'status': 'tp1', 'R': round(r1, 3), 'exit': t1, 'closedTs': hit1ts}
    if hit1:
        return {'status': 'tp1', 'R': round(r1, 3), 'exit': t1, 'closedTs': hit1ts}
    if len(bars) - j < HZ:
        return None
    last = bars[j + HZ - 1]
    return {'status': 'timeout', 'R': round(d * (last['c'] - e) / risk, 3), 'exit': last['c'], 'closedTs': last['t'] * 1000}


# 1) proposte aperte da chiudere
updates = []
for pid, p in props.items():
    if p.get('status') != 'open' or p.get('symbol') not in tail:
        continue
    bars = [b for b in tail[p['symbol']] if b['t'] * 1000 + 86400000 <= now]  # solo candele chiuse
    r = eval_p(p, bars)
    if r:
        updates.append({'doc_id': pid, 'fields': r}); p.update(r)

# 2) proposte nuove dalla scansione del cloud
sop = {}
if sop_path and os.path.exists(sop_path):
    st = json.load(open(sop_path))
    if now - st.get('lastRun', 0) < 12 * 3600000:
        sop = {a['sym']: a['bias'] for a in st.get('assets', [])}
new, skipped = [], []
fresh = now - scan.get('at', 0) < 36 * 3600000
for c in cands if fresh else []:
    d = c['doc']; sym, dr = d['symbol'], int(d['dir'])
    if not ID_RE.match(c['id']):
        skipped.append((sym, 'simbolo non salvabile nel database')); continue
    if c['id'] in props:
        skipped.append((sym, 'già nel registro')); continue
    if any(q.get('symbol') == sym and int(q.get('dir', 0)) == dr and (q.get('status') == 'open' or q.get('date') == d['date']) for q in props.values()):
        skipped.append((sym, 'già aperta o già proposta oggi')); continue
    busy = sum(1 for q in props.values() if q.get('status') == 'open' and int(q.get('v') or 1) >= 2 and int(q.get('dir', 0)) == dr
               and q.get('cluster') == d.get('cluster') and q.get('symbol') != sym)
    if busy >= MAX_CLUSTER:
        skipped.append((sym, 'gruppo pieno')); continue
    if sym.startswith('BINANCE:') and sop:
        b = sop.get(sym.split(':')[1].replace('USDT', ''))
        if b:
            d['sop'] = 'neutro' if b == 'wait' else ('concorde' if (b == 'long') == (dr > 0) else 'discorde')
    d['cloud'] = True
    new.append({'doc_id': c['id'], 'data': d}); props[c['id']] = d

plan = {
    'scan': scan if scan.get('at', 0) > float(db_scan.get('at', 0) or 0) else None,
    'scan_at': scan.get('at'), 'scan_fresh': fresh,
    'new': new, 'updates': updates, 'skipped': skipped,
}
emit = os.environ.get('EMIT_DIR')
if emit:
    os.makedirs(emit, exist_ok=True)
    for i, n in enumerate(plan['new']):
        json.dump(n['data'], open(os.path.join(emit, f'new_{i}.json'), 'w'), ensure_ascii=False); n['file'] = os.path.join(emit, f'new_{i}.json')
    for i, u in enumerate(plan['updates']):
        json.dump(u['fields'], open(os.path.join(emit, f'upd_{i}.json'), 'w')); u['file'] = os.path.join(emit, f'upd_{i}.json')
    if plan['scan']:
        json.dump(plan['scan'], open(os.path.join(emit, 'scan.json'), 'w'), ensure_ascii=False); plan['scan_file'] = os.path.join(emit, 'scan.json')
    plan['scan'] = bool(plan['scan'])
json.dump(plan, sys.stdout, ensure_ascii=False, indent=1)
print(f"\n# nuove {len(new)}, chiuse {len(updates)}, scartate {len(skipped)}, scansione nuova: {scan.get('at', 0) > float(db_scan.get('at', 0) or 0)}", file=sys.stderr)
