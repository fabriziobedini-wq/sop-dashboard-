# SOP Strategy Monitor — archiviato il 28/10/2026

Decisione di Fabrizio: fermare il monitoraggio live del sistema nella sua forma attuale (regole al 28/10/2026).
Niente è stato cancellato: codice, dati e storico restano in questo repository. Nessun broker, nessuna chiave API, nessun ordine reale è mai stato collegato.

## Numeri finali (dati documentati nel repo)
- **Registro segnali consigliati, 18/10 → 28/10 (simulato su candele 15m OKX):** 44 segnali veri, 32 chiusi, **0 vincenti**, **0 hanno raggiunto TP1**; 20 stop e 12 pareggi; risultato **-48,06%** (media -1,50% a trade). Altri 12 ancora aperti al momento dell'archiviazione.
- **Segnali "ombra" (bloccati dal filtro MA20):** 11 chiusi, -25,57%.
- **Nuovo percorso del dashboard (trade aperti da Fabrizio dal 1/10):** 5 chiusi, +2,95%, 40% vincenti (campione piccolo).
- **Storico completo del dashboard (60 chiusi attivati):** -35,77%; 56 senza i 4 stop sfondati: +66,03% (dato dominato da pochi trade, non affidabile).

## Cosa è documentato e cosa no
- Documentato: nei 10 giorni misurati le regole attuali non hanno prodotto nemmeno un trade che raggiungesse TP1; la simulazione concorda con TradingView sui due segnali controllati a mano (BNB, rimbalzo ETH del 20/10).
- Non stabilito: la causa (assenza di vantaggio dei segnali, stop ~2,5% troppo stretto, periodo di mercato avverso). Non è stato fatto un backtest su storico lungo.
- Il campione è breve e i segnali sono correlati (molti short insieme): "fallimento" vale per queste regole in questo periodo, non è una prova sul metodo SOP in generale.

## Cosa è stato fatto per archiviare
- Workflow GitHub Actions `sop_monitor_v2.yml` disattivato (niente più segnali Telegram e registrazioni).
- Task programmato "SOP Trade Sync" disattivato.

## Come riattivarlo
- GitHub → Actions → "SOP Strategy Monitor v2" → Enable workflow.
- Riattivare il task programmato "SOP Trade Sync".
- Idea non eseguita: backtest sulle candele storiche OKX (pattern + EMA20/50 + stesse regole di stop/TP) per capire se stop o pattern sono il problema.

## Backtest del 28/10/2026 (storico OKX 20/02 → 28/10/2026, 9 asset, 4h + 1h)
Dettagli e tabelle: `BACKTEST.md` e `backtest_results.json`. Solo la parte price action (pattern + stop/TP del backend), pattern valutati in entrambe le direzioni, senza commissioni né slippage. Il bias da OI/funding/CVD NON è stato testato (storico troppo corto).
- **Pattern vs entrate casuali con le stesse regole di stop/TP:** n=1301 pattern contro 1744 casuali. TP1 raggiunto nel 18,4% contro 20,1%; media -0,034R contro -0,003R. Differenza di circa 1 errore standard: nessun vantaggio dimostrato, e prima dei costi.
- **Allargare lo stop (2,5×ATR) o filtrare per trend (SMA20):** non cambia il quadro, nessuna combinazione positiva in modo robusto.
- **Short -0,077R (n=633) contro long +0,006R (n=668);** ultimi 30 giorni del campione -0,234R: periodo sfavorevole ai pattern.
- **Rejection EMA20 (short):** n=141, TP1 12%, -0,292R: il pattern che il live ha usato di più ed è il peggiore del backtest (indizio, non prova: sono 11 pattern confrontati).
- **Live 18–28/10:** 0 TP1 su 32 chiusi. Il backtest ne farebbe aspettare circa 6: più sfortunato/avverso del backtest, causa non stabilita (campione corto e correlato, regime, oppure il livello di bias OI/funding/CVD che il backtest non copre).
- **Conclusione:** per il livello price action non c'è evidenza di vantaggio. Il bias OI/funding/CVD resta non misurato.
