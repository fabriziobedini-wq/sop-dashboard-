"""
asset_universe.py — Modulo di selezione dell'universo tradabile per SOP Strategy Monitor.

PROBLEMA RISOLTO
----------------
Il sistema selezionava gli asset da tradare come "top 10 per Open Interest"
(da Binance API). OI non equivale a market cap: un token a bassa
capitalizzazione può avere OI alto per hype/leva speculativa. Questo ha
fatto entrare nell'universo tradabile asset come LAB e TAIKO, causando le
due perdite catastrofiche del backtest (-65,52% e -34,32%) quando lo stop
ATR-based è stato sfondato da un gap di illiquidità.

FIX
---
L'universo tradabile ora è: top 10 crypto per MARKET CAP + commodities
(oro, argento) + RWA/titoli azionari. OI/Volume restano utili SOLO
all'interno di questo universo già filtrato, per calcolare il regime di
mercato (Strutturale/Misto/Momentum) — non per decidere quali asset
entrano nell'universo.

USO
---
    from asset_universe import get_tradable_universe, is_asset_allowed

    universe = get_tradable_universe()          # lista completa ammessa
    if not is_asset_allowed(asset_symbol):
        continue                                # salta l'asset, non è ammesso
"""

import requests

# ---------------------------------------------------------------------------
# 1. WHITELIST STATICA — utilizzabile da subito, aggiornala manualmente
#    ogni 1-3 mesi (la top 10 per market cap non cambia spesso).
#    Ultimo aggiornamento: 08/07/2026 — fonte: CoinMarketCap, esclusi stablecoin
# ---------------------------------------------------------------------------
STATIC_TOP10_MARKETCAP = [
    "BTC", "ETH", "BNB", "XRP", "SOL", "TRX", "HYPE", "DOGE", "LEO", "ZEC"
]

COMMODITIES = ["XAU", "XAG"]  # oro, argento

RWA_STOCKS = [
    "MU", "SOXL", "SKHYNIX",
    # aggiungi qui gli altri ticker RWA/azionari che tradi su OKX/Bybit
]

# Stablecoin da escludere sempre, anche se compaiono per market cap
STABLECOIN_EXCLUDE = {"USDT", "USDC", "DAI", "USDE", "USD1", "PYUSD", "FDUSD", "USDD"}


# ---------------------------------------------------------------------------
# 2. WHITELIST DINAMICA — CoinGecko (nessuna API key richiesta sul tier free)
# ---------------------------------------------------------------------------
COINGECKO_URL = "https://api.coingecko.com/api/v3/coins/markets"


def get_top10_by_marketcap(exchange_tradable_symbols=None):
    """
    Ritorna la top 10 crypto per market cap, esclusi gli stablecoin.

    exchange_tradable_symbols: set opzionale di ticker effettivamente
        disponibili come perpetual su OKX/Bybit. Se fornito, filtra il
        risultato solo su quelli, per evitare di includere coin con
        market cap alto ma senza perpetual tradabile.
    """
    try:
        params = {
            "vs_currency": "usd",
            "order": "market_cap_desc",
            "per_page": 30,  # margine per compensare stablecoin/esclusi
            "page": 1,
            "sparkline": "false",
        }
        resp = requests.get(COINGECKO_URL, params=params, timeout=10)
        resp.raise_for_status()
        data = resp.json()

        top10 = []
        for coin in data:
            symbol = coin["symbol"].upper()
            if symbol in STABLECOIN_EXCLUDE:
                continue
            if exchange_tradable_symbols and symbol not in exchange_tradable_symbols:
                continue
            top10.append(symbol)
            if len(top10) == 10:
                break

        if len(top10) < 10:
            # fallback parziale: completa con la whitelist statica
            for s in STATIC_TOP10_MARKETCAP:
                if s not in top10:
                    top10.append(s)
                if len(top10) == 10:
                    break

        return top10

    except Exception as e:
        print(f"[asset_universe] Errore fetch CoinGecko, uso whitelist statica: {e}")
        return STATIC_TOP10_MARKETCAP.copy()


# ---------------------------------------------------------------------------
# 3. UNIVERSO TRADABILE COMPLETO
# ---------------------------------------------------------------------------
def get_tradable_universe(use_dynamic=True, exchange_tradable_symbols=None):
    """
    Ritorna la lista completa degli asset ammessi dal metodo SOP:
    top 10 market cap + commodities + RWA/titoli.
    Tutto il resto ("merda") è escluso a priori dal generatore di segnali.
    """
    crypto = (
        get_top10_by_marketcap(exchange_tradable_symbols)
        if use_dynamic
        else STATIC_TOP10_MARKETCAP.copy()
    )
    return crypto + COMMODITIES + RWA_STOCKS


def is_asset_allowed(symbol, universe=None):
    """Controllo rapido da usare prima di generare qualunque segnale."""
    universe = universe or get_tradable_universe()
    return symbol.upper() in [u.upper() for u in universe]


if __name__ == "__main__":
    universe = get_tradable_universe()
    print("Universo tradabile SOP:", universe)
