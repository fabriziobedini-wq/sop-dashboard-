# Backtest "fine della discesa" (2026-11-14 22:53 UTC)

Periodo 01/11/2024 → 31/10/2026, candele 4h dei futures Binance su 10 crypto. Solo momenti con prezzo almeno 10% sotto il massimo di 20 giorni. Entrata alla candela successiva, costi 0,1%, operazioni non sovrapposte (72 ore) sullo stesso asset.

| Regola di riacquisto | Casi | Uscita a 72 ore | Uscita a 7 giorni | Stop e target 2:1 (max 7 giorni) | 1° anno (stop/target) | 2° anno (stop/target) | Asset positivi |
|---|---|---|---|---|---|---|---|
| Confronto: ricomprare in un momento qualsiasi della discesa | 1206 | -0.30% (49% vinte, t -1.54) | -1.24% (43% vinte, t -4.25) | -0.95% (30% vinte, t -5.55) | -0.89% (33% vinte, t -3.4) | -1.01% (27% vinte, t -4.84) | 0/10 |
| Almeno 2 condizioni su 7 | 1101 | -0.16% (48% vinte, t -0.79) | -1.02% (44% vinte, t -3.37) | -0.92% (33% vinte, t -4.91) | -0.76% (36% vinte, t -2.56) | -1.12% (29% vinte, t -5.15) | 0/10 |
| Almeno 3 condizioni su 7 | 856 | -0.15% (46% vinte, t -0.65) | -1.02% (44% vinte, t -3.07) | -0.92% (34% vinte, t -3.88) | -0.45% (39% vinte, t -1.16) | -1.44% (28% vinte, t -5.53) | 0/10 |
| Almeno 4 condizioni su 7 | 474 | -0.09% (44% vinte, t -0.31) | -0.82% (43% vinte, t -1.97) | -1.02% (36% vinte, t -3.12) | -1.03% (38% vinte, t -2.01) | -1.02% (34% vinte, t -2.52) | 1/10 |
| Almeno 5 condizioni su 7 | 174 | -1.34% (40% vinte, t -2.96) | -1.22% (45% vinte, t -2.0) | -1.50% (39% vinte, t -2.86) | -1.92% (38% vinte, t -2.16) | -1.13% (39% vinte, t -1.88) | 2/10 |
| Almeno 6 condizioni su 7 | 18 | -4.34% (17% vinte, t -2.75) | -2.48% (33% vinte, t -1.82) | -2.56% (33% vinte, t -1.95) | -8.22% (0% vinte, t -3.29) | -0.38% (46% vinte, t -0.35) | 0/8 |
| Solo condizione 1 cascata liquidazioni long | 102 | +4.02% (70% vinte, t 5.56) | +0.96% (57% vinte, t 1.04) | +0.26% (36% vinte, t 0.7) | +0.96% (49% vinte, t 1.47) | -0.43% (24% vinte, t -1.27) | 5/10 |
| Solo condizione 2 folla non più long estrema | 950 | +0.01% (48% vinte, t 0.06) | -0.83% (44% vinte, t -2.53) | -0.84% (33% vinte, t -4.14) | -0.62% (36% vinte, t -1.9) | -1.08% (30% vinte, t -4.59) | 1/10 |
| Solo condizione 3 leva scaricata (OI -10%) | 671 | +0.04% (50% vinte, t 0.12) | -1.30% (41% vinte, t -3.27) | -1.23% (27% vinte, t -5.89) | -1.30% (28% vinte, t -4.42) | -1.12% (26% vinte, t -4.06) | 3/10 |
| Solo condizione 4 funding negativo | 820 | -0.32% (47% vinte, t -1.33) | -1.18% (44% vinte, t -3.47) | -0.91% (30% vinte, t -4.84) | -0.86% (32% vinte, t -2.85) | -0.96% (28% vinte, t -4.19) | 2/10 |
| Solo condizione 5 tornano gli acquisti aggressivi | 298 | -0.72% (44% vinte, t -2.31) | -0.33% (48% vinte, t -0.63) | -0.11% (41% vinte, t -0.3) | +0.59% (45% vinte, t 0.76) | -0.47% (38% vinte, t -1.16) | 4/10 |
| Solo condizione 6 prezzo sopra media 20 (4h) | 662 | -0.72% (42% vinte, t -2.74) | -1.17% (44% vinte, t -2.95) | -1.03% (38% vinte, t -3.48) | -0.85% (40% vinte, t -1.91) | -1.25% (34% vinte, t -3.37) | 0/10 |
| Solo condizione 7 minimo crescente (4h) | 897 | -0.40% (44% vinte, t -1.75) | -0.85% (43% vinte, t -2.53) | -0.97% (34% vinte, t -4.15) | -0.27% (39% vinte, t -0.75) | -1.82% (27% vinte, t -6.87) | 1/10 |
| Liquidazioni + folla non più estrema + una conferma di prezzo (6 o 7) | 73 | -1.87% (41% vinte, t -2.16) | -2.81% (36% vinte, t -2.98) | -2.81% (27% vinte, t -3.87) | -3.41% (31% vinte, t -2.97) | -2.22% (24% vinte, t -2.48) | 3/10 |
| Leva scaricata + folla non più estrema + una conferma di prezzo (6 o 7) | 298 | -0.46% (48% vinte, t -1.23) | -0.98% (40% vinte, t -1.77) | -1.48% (31% vinte, t -3.33) | -1.22% (34% vinte, t -1.92) | -1.88% (25% vinte, t -3.44) | 2/10 |

Una regola vale qualcosa solo se batte il confronto in entrambi gli anni e su quasi tutti gli asset. La quota di stablecoin (USDT dominance) non è nell'archivio e non è testata.
