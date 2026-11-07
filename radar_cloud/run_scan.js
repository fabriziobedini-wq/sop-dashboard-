// Esegue la scansione Scopri della pagina radar.html in un browser senza schermo, con le stesse regole della pagina.
// Le candele arrivano da out/bars.json al posto di TradingView; il database è simulato in memoria.
// Scrive out/scan_latest.json (come scans/latest), out/candidates.json (proposte nuove) e out/bars_tail.json.
const { chromium } = require('playwright');
const fs = require('fs'), path = require('path');
const DIR = __dirname, OUT = path.join(DIR, 'out');
const bars = JSON.parse(fs.readFileSync(path.join(OUT, 'bars.json'), 'utf8'));
const html = fs.readFileSync(path.join(DIR, 'radar.html'), 'utf8');

const stub = `(()=>{
  try{ localStorage.setItem("radar.list", JSON.stringify(["TVC:GOLD"])); localStorage.setItem("radar.v","3"); localStorage.setItem("radar.tf",JSON.stringify("1D")); }catch(e){}
  const BARS = window.__BARS; const store = {}; window.__store = store;
  const mcp = Object.freeze({ callTool(server, tool, input){
      if(tool === "mcp-tv-get-ohlcv"){ const b = BARS[input.symbol]; if(!b) return Promise.reject(new Error("simbolo non disponibile"));
        return Promise.resolve({content:[], payload:{bars: b.slice(-(input.count||300))}}); }
      if(tool === "mcp-tv-get-news") return Promise.resolve({content:[], payload:{data:{headlines:[]}}});
      if(tool === "mcp-tv-get-earnings-calendar") return Promise.resolve({content:[], payload:{data:[]}});
      return Promise.resolve({content:[], payload:{data:{symbols:[]}}}); },
    listTools(){ return Promise.resolve({servers:[]}); } });
  const subs = [];
  const snap = n => { const docs = Object.entries(store[n]||{}).map(([id,d])=>({id, exists:true, data:()=>d})); return {docs, size:docs.length, empty:!docs.length, docChanges:()=>[]}; };
  const notify = n => subs.filter(s=>s[0]===n).forEach(s=>setTimeout(()=>s[1](snap(n)),5));
  function coll(p){ const n = p.split("/").pop(); const q = {
      orderBy(){return q}, limit(){return q}, where(){return q},
      get(){ return Promise.resolve(snap(n)); },
      onSnapshot(cb){ subs.push([n,cb]); setTimeout(()=>cb(snap(n)),20); return ()=>{}; },
      doc(id){ id = id || Math.random().toString(36).slice(2); return {
        id,
        set(d){ (store[n] = store[n]||{})[id] = JSON.parse(JSON.stringify(d)); notify(n); return Promise.resolve(); },
        update(d){ const x = (store[n]||{})[id]; if(x) Object.assign(x, d); notify(n); return Promise.resolve(); },
        delete(){ if(store[n]) delete store[n][id]; notify(n); return Promise.resolve(); },
        onSnapshot(cb){ setTimeout(()=>{ const x=(store[n]||{})[id]; cb(x?{exists:true,data:()=>x}:{exists:false,data:()=>undefined}); },20); return ()=>{}; } }; },
      add(d){ const r = this.doc(); return r.set(d).then(()=>r); } }; return q; }
  const db = Object.freeze({ collection: coll, doc: p => { const a = p.split("/"); return coll(a[0]).doc(a[1]); } });
  window.claude = { use(n){ return Promise.resolve(n==="mcp"?mcp:n==="db"?db:null); } };
})();`;

(async () => {
  const exe = process.env.CHROME_PATH || undefined;
  const b = await chromium.launch(exe ? { executablePath: exe } : {});
  const pg = await b.newPage();
  const errs = []; pg.on('pageerror', e => errs.push(e.message));
  await pg.route(/fonts\./, r => r.abort());
  await pg.route('http://radar.local/**', r => r.fulfill({ status: 200, contentType: 'text/html', body: html }));
  await pg.addInitScript(`window.__BARS=${JSON.stringify(bars)};`);
  await pg.addInitScript(stub);
  await pg.goto('http://radar.local/');
  await pg.waitForTimeout(4000);
  await pg.evaluate(() => document.getElementById('scan').click());
  const t0 = Date.now();
  while (Date.now() - t0 < 600000) {
    const done = await pg.evaluate(() => !!(window.__store.scans && window.__store.scans.latest));
    if (done) break;
    await pg.waitForTimeout(2000);
  }
  await pg.waitForTimeout(3000);
  const st = await pg.evaluate(() => window.__store);
  await b.close();
  if (!st.scans || !st.scans.latest) { console.error('scansione non completata', errs); process.exit(1); }
  const cand = Object.entries(st.proposals || {}).map(([id, doc]) => ({ id, doc })).filter(x => x.doc.source === 'scopri');
  fs.writeFileSync(path.join(OUT, 'scan_latest.json'), JSON.stringify(st.scans.latest));
  fs.writeFileSync(path.join(OUT, 'candidates.json'), JSON.stringify(cand, null, 1));
  const tail = {}; for (const [s, arr] of Object.entries(bars)) tail[s] = arr.slice(-90);
  fs.writeFileSync(path.join(OUT, 'bars_tail.json'), JSON.stringify(tail));
  console.log(`scansione: ${st.scans.latest.rows.length} asset analizzati, ${st.scans.latest.fail} non riusciti, ${cand.length} proposte nuove; errori pagina: ${errs.length ? errs.join(' | ') : 'nessuno'}`);
})();
