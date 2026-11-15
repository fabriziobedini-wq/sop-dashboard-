# Monte Carlo e replay dei segnali futures (2026-11-15 06:51 UTC)

Regola: entrata alla candela 4h dopo il segnale, uscita dopo 72 ore, nessuno stop. 1R = k × ATR(4h) all'entrata, con k = 95° percentile della peggior escursione contraria. Monte Carlo: 5.000 sequenze di 100 operazioni pescate a caso dalla storia. Replay: le operazioni reali in ordine di tempo, sovrapposte come sono avvenute.

## Liquidazioni

121 operazioni in 2 anni (circa 60 all'anno), 63% vinte, media +2.73% = +0.060 R. 1R = 7.45 ATR (escursione contraria mediana 1.4 ATR). Peggiore -2.83 R, migliore 1.16 R.

| Rischio per operazione (1R) | Replay: risultato 2 anni | Replay: peggior calo | MC 100 operazioni: risultato mediano | MC: calo mediano | MC: calo nel 5% dei casi peggiori | MC: calo nell'1% peggiore | MC: probabilità di chiudere in perdita | MC: serie di perdite (95%) |
|---|---|---|---|---|---|---|---|---|
| 0.5% | +3.6% | −2.9% | +3.0% | −1.7% | −3.7% | −4.8% | 11.3% | 7 di fila |
| 1% | +7.3% | −5.7% | +6.1% | −3.4% | −7.3% | −9.5% | 11.6% | 7 di fila |
| 2% | +14.9% | −11.2% | +12.3% | −6.8% | −14.3% | −18.2% | 12.1% | 7 di fila |

## Folla estrema

811 operazioni in 2 anni (circa 406 all'anno), 51% vinte, media +0.70% = +0.051 R. 1R = 5.47 ATR (escursione contraria mediana 1.7 ATR). Peggiore -8.87 R, migliore 3.43 R.

| Rischio per operazione (1R) | Replay: risultato 2 anni | Replay: peggior calo | MC 100 operazioni: risultato mediano | MC: calo mediano | MC: calo nel 5% dei casi peggiori | MC: calo nell'1% peggiore | MC: probabilità di chiudere in perdita | MC: serie di perdite (95%) |
|---|---|---|---|---|---|---|---|---|
| 0.5% | +22.6% | −7.9% | +2.8% | −2.1% | −6.2% | −8.5% | 21.4% | 9 di fila |
| 1% | +48.8% | −15.4% | +5.5% | −4.3% | −12.3% | −16.6% | 21.9% | 9 di fila |
| 2% | +112.4% | −29.5% | +10.8% | −8.4% | −23.8% | −31.6% | 23.3% | 9 di fila |

Il Monte Carlo pesca le operazioni come se fossero indipendenti; nella realtà i segnali su più crypto arrivano insieme (stesso movimento di mercato), e il replay storico lo mostra: per questo il budget limita le operazioni aperte nello stesso momento.
