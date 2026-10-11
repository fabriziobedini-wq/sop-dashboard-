# Sync Log

Log automatico dei sync tra la dashboard SOP Strategy Monitor (localStorage del browser) e `open_trades.json`. Una riga per ogni sync in cui sono comparsi nuovi trade chiusi.

- 2026-10-03 19:06 UTC: 68 trade chiusi, win rate 42.11%, pnl totale -38.72% — primo sync reale: open_trades.json era vuoto, quindi questo batch copre l'intero storico. Anomalia degna di nota: su LAB (stop a -11% dall'entry, chiuso a -65.52%) e HYPE (stop a -2% dall'entry, chiuso a -11.42%) lo stop non è stato rispettato, probabile gap/slippage non gestito dal motore di chiusura.
- 2026-10-11 18:12 UTC: 2 trade chiusi (BTC long +1.67% bias_inverted_24h, XRP short +2.75% tp2), 3 nuovi aperti (TRX, BTC, ZEC long) — sync fatto in sessione interattiva; la sync schedulata non aveva scritto nulla dopo il 3 ott. Totale chiusi attivati: 57, WR 45.6%, pnl -34.30% (+67.50% senza i 4 stop sfondati). Dettagli in RELIABILITY.md.
