#!/usr/bin/env python3
"""Prepara il documento crypto/oggi per il database del radar: fotografia derivati + registro segnali futures."""
import json, sys, time, os
d = os.path.dirname(os.path.abspath(__file__))
oggi = json.load(open(os.path.join(d, 'crypto_oggi.json')))
reg_p = os.path.join(d, 'segnali_futures.json')
reg = json.load(open(reg_p)) if os.path.exists(reg_p) else []
out = sys.argv[1] if len(sys.argv) > 1 else 'crypto_oggi_doc.json'
json.dump({'at': int(time.time() * 1000), 'creato': oggi.get('creato'), 'archivio_fino_a': oggi.get('archivio_fino_a'),
           'asset': oggi.get('asset', {}), 'mercato': oggi.get('mercato'), 'registro': reg[-200:]}, open(out, 'w'), ensure_ascii=False)
print('crypto/oggi pronto:', len(oggi.get('asset', {})), 'crypto,', len(reg), 'segnali nel registro,', os.path.getsize(out), 'byte')
