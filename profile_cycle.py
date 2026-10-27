"""Mesure où passe le temps d'un passage du bot (lecture seule)."""
import time

import MetaTrader5 as mt5

import live_mt5 as bot

mt5.initialize()
for sym in ["Volatility 75 Index", "EURUSDmicro", "XAUUSD"]:
    mt5.symbol_select(sym, True)
    for tf in ("H1", "H4", "D1", "W1"):
        t = time.time()
        df = bot.rates(sym, tf)
        print(f"{sym:22} {tf} chargement MT5 : {time.time() - t:5.2f}s ({0 if df is None else len(df)} bougies)")
    t = time.time()
    h = bot.compute_htf(sym)
    print(f"{sym:22} compute_htf total : {time.time() - t:5.2f}s\n")
mt5.shutdown()
