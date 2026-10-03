# Sync Log

Log automatico dei sync tra la dashboard SOP Strategy Monitor (localStorage del browser) e `open_trades.json`. Una riga per ogni sync in cui sono comparsi nuovi trade chiusi.

- 2026-10-03 19:06 UTC: 68 trade chiusi, win rate 42.11%, pnl totale -38.72% — primo sync reale: open_trades.json era vuoto, quindi questo batch copre l'intero storico. Anomalia degna di nota: su LAB (stop a -11% dall'entry, chiuso a -65.52%) e HYPE (stop a -2% dall'entry, chiuso a -11.42%) lo stop non è stato rispettato, probabile gap/slippage non gestito dal motore di chiusura.
