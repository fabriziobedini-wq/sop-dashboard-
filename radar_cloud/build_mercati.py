#!/usr/bin/env python3
"""Prepara il documento mercati/oggi per la pagina Oggi del radar: tutti gli asset della scansione notturna
(azioni USA ed Europa, ETF, materie prime, crypto) con variazioni, giudizio del radar e operazioni proposte.
Nessuna richiesta a TradingView: usa radar_cloud/out (candele Yahoo/Binance scaricate dal workflow notturno)."""
import json, os, sys, time
D = os.path.dirname(os.path.abspath(__file__))
scan = json.load(open(os.path.join(D, 'out', 'scan_latest.json')))
tail = json.load(open(os.path.join(D, 'out', 'bars_tail.json')))
cand = json.load(open(os.path.join(D, 'out', 'candidates.json')))
ETF = {'XLK', 'XLF', 'XLE', 'XLV', 'XLI', 'XLU', 'SMH', 'GDX', 'EEM', 'EWZ', 'FXI', 'QQQ', 'TLT', 'IWM', 'SPY'}
NAMES = {'XLK': 'Tecnologia', 'XLF': 'Finanza', 'XLE': 'Energia', 'XLV': 'Salute', 'XLI': 'Industria', 'XLU': 'Utility', 'SMH': 'Semiconduttori',
         'GDX': "Minatori d'oro", 'EEM': 'Emergenti', 'EWZ': 'Brasile', 'FXI': 'Cina', 'QQQ': 'Nasdaq 100', 'TLT': 'Treasury 20+ anni', 'IWM': 'Small cap USA',
         'SILVER': 'Argento', 'USOIL': 'Petrolio WTI', 'PLATINUM': 'Platino', 'HG1!': 'Rame', 'NG1!': 'Gas naturale', 'ZS1!': 'Soia', 'ZW1!': 'Grano', 'ZC1!': 'Mais', 'GOLD': 'Oro'}


def group(sym):
    ex, t = sym.split(':')
    if ex == 'BINANCE': return 'Crypto'
    if t in ETF: return 'ETF: settori, paesi e obbligazioni'
    if ex in ('TVC', 'COMEX', 'NYMEX', 'CBOT'): return 'Materie prime'
    if ex in ('MIL', 'XETR', 'EURONEXT'): return 'Azioni Europa'
    return 'Azioni USA'


def chg(b, n):
    return round((b[-1]['c'] / b[-1 - n]['c'] - 1) * 100, 2) if len(b) > n else None


ops = {}
for c in cand:
    d = c['doc']; ops.setdefault(d['symbol'], []).append({'lato': 'compra' if d['dir'] > 0 else 'vendi', 'entrata': d['entry'], 'stop': d['stop'], 'target': d['tp1'], 'solidita': d.get('grade')})
G = {}
for r in scan['rows']:
    s = r['symbol']; b = tail.get(s, [])
    t = s.split(':')[1].replace('USDT', '')
    G.setdefault(group(s), []).append({'sym': s, 'nome': NAMES.get(t, t), 'prezzo': r.get('live'), 'g1': chg(b, 1), 'g7': r.get('ch7'), 'g30': r.get('ch30'),
                                        'giudizio': r.get('k'), 'punteggio': r.get('score'), 'bias': r.get('bias'), 'proposte': ops.get(s, [])})
order = ['Azioni USA', 'Azioni Europa', 'ETF: settori, paesi e obbligazioni', 'Materie prime', 'Crypto']
doc = {'at': int(time.time() * 1000), 'scan_at': scan.get('at'), 'gruppi': [{'nome': g, 'asset': G[g]} for g in order if g in G]}
out = sys.argv[1] if len(sys.argv) > 1 else 'mercati_oggi_doc.json'
json.dump(doc, open(out, 'w'), ensure_ascii=False)
print('mercati/oggi pronto:', sum(len(g['asset']) for g in doc['gruppi']), 'asset,', sum(len(a['proposte']) for g in doc['gruppi'] for a in g['asset']), 'proposte,', os.path.getsize(out), 'byte')
