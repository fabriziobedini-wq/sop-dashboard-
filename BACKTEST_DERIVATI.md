# Backtest SOP — squilibri dei derivati (2026-11-07 14:02 UTC)

Periodo 01/11/2024 → 31/10/2026, barre da 4 ore, futures perpetui Binance su 10 crypto: BTC, ETH, SOL, XRP, BNB, DOGE, ADA, LINK, AVAX, TRX (43740 barre in totale).
Ogni segnale entra all'apertura della barra successiva ed esce dopo 24 o 72 ore. Risultato netto di 0.1% di costi. Segnali non sovrapposti sullo stesso asset.
Media = rendimento medio per operazione in %, nella direzione del segnale. t = forza statistica (sopra 2,5 e positivo in entrambi gli anni = vantaggio robusto). "Caso" = cosa avresti ottenuto con la stessa quota di long e short presi a caso.

| Segnale | Orizzonte | Casi | Vinte | Media | t | 1° anno | 2° anno | Caso | Asset positivi | Giudizio |
|---|---|---|---|---|---|---|---|---|---|---|
| SOP bias (come nel backend) | 24h | 5601 | 46% | -0.01% | -0.13 | +0.04% | -0.05% | -0.09% | 4/10 | nessun vantaggio |
| SOP bias (come nel backend) | 72h | 2190 | 47% | -0.11% | -0.78 | -0.04% | -0.18% | -0.09% | 3/10 | nessun vantaggio |
| SOP bias con CVD vero | 24h | 5368 | 48% | -0.10% | -1.73 | -0.19% | -0.01% | -0.13% | 2/10 | nessun vantaggio |
| SOP bias con CVD vero | 72h | 2158 | 49% | -0.15% | -1.03 | -0.51% | +0.21% | -0.20% | 2/10 | nessun vantaggio |
| Funding estremo, contrarian | 24h | 1340 | 49% | -0.27% | -2.31 | -0.33% | -0.21% | -0.10% | 1/10 | PERDENTE |
| Funding estremo, contrarian | 72h | 781 | 52% | +0.04% | 0.15 | +0.09% | -0.01% | -0.11% | 4/10 | nessun vantaggio |
| Long/short top trader estremo, contrarian | 24h | 1828 | 49% | -0.14% | -1.37 | -0.19% | -0.09% | -0.10% | 3/10 | nessun vantaggio |
| Long/short top trader estremo, contrarian | 72h | 879 | 51% | -0.06% | -0.24 | -0.04% | -0.07% | -0.10% | 4/10 | nessun vantaggio |
| Long/short folla estremo, contrarian | 24h | 1520 | 50% | +0.17% | 1.59 | +0.19% | +0.14% | -0.10% | 7/10 | nessun vantaggio |
| Long/short folla estremo, contrarian | 72h | 810 | 51% | +0.72% | 2.87 | +0.89% | +0.52% | -0.10% | 9/10 | VANTAGGIO (robusto) |
| Volume aggressivo estremo, segue | 24h | 2696 | 51% | +0.04% | 0.5 | -0.02% | +0.08% | -0.10% | 3/10 | nessun vantaggio |
| Volume aggressivo estremo, segue | 72h | 1502 | 49% | -0.17% | -1.07 | -0.24% | -0.10% | -0.10% | 5/10 | nessun vantaggio |
| OI in forte aumento, segue il prezzo | 24h | 1117 | 46% | +0.12% | 0.8 | +0.31% | -0.05% | -0.10% | 7/10 | nessun vantaggio |
| OI in forte aumento, segue il prezzo | 72h | 815 | 39% | -0.42% | -1.7 | -0.28% | -0.56% | -0.11% | 2/10 | nessun vantaggio |
| OI in forte calo, contro il prezzo | 24h | 1296 | 51% | +0.22% | 2.01 | +0.57% | -0.14% | -0.10% | 6/10 | indizio positivo, non robusto |
| OI in forte calo, contro il prezzo | 72h | 938 | 51% | +0.41% | 1.89 | +1.08% | -0.28% | -0.11% | 7/10 | nessun vantaggio |
| Liquidazioni (sostituto), contrarian | 24h | 127 | 54% | +1.82% | 3.27 | +3.48% | +0.29% | -0.04% | 9/10 | VANTAGGIO (robusto) |
| Liquidazioni (sostituto), contrarian | 72h | 121 | 63% | +2.73% | 3.78 | +4.28% | +1.20% | +0.08% | 9/10 | VANTAGGIO (robusto) |
| Funding estremo + OI in aumento, contrarian | 24h | 810 | 48% | -0.35% | -1.81 | -0.56% | -0.17% | -0.10% | 2/10 | nessun vantaggio |
| Funding estremo + OI in aumento, contrarian | 72h | 573 | 45% | -0.76% | -2.62 | -1.00% | -0.55% | -0.10% | 1/10 | PERDENTE |

Le liquidazioni non sono nell'archivio pubblico: il segnale "Liquidazioni (sostituto)" usa una barra con movimento oltre 2,5 ATR e calo dell'open interest oltre il 2%.
Attenzione: sono 10 segnali × 2 orizzonti = 20 prove. Per puro caso una su venti può sembrare buona: conta solo un risultato forte (t ≥ 2,5) e positivo in entrambi gli anni.
