"""H1 contre M15 avec le VRAI spread de ton broker (lu dans MT5) : la stratégie survit-elle aux coûts ?

Usage : python tf_test.py          (MT5 ouvert, lecture seule)
Entrée en M15 : lignes de tendance tracées en W1 / D1 / H4 / H1 (descente d'une échelle de plus).
"""
from dataclasses import replace

import MetaTrader5 as mt5
import pandas as pd

from data import get_candles
from mtf import MTFParams, backtest_mtf
from strategy import stats

MARKETS = {  # nom : (code Deriv, symbole MT5)
    "Volatility 10": ("R_10", "Volatility 10 Index"), "Volatility 25": ("R_25", "Volatility 25 Index"),
    "Volatility 50": ("R_50", "Volatility 50 Index"), "Volatility 75": ("R_75", "Volatility 75 Index"),
    "Volatility 100": ("R_100", "Volatility 100 Index"), "Step Index": ("stpRNG", "Step Index"),
    "EUR/USD": ("frxEURUSD", "EURUSD"), "GBP/USD": ("frxGBPUSD", "GBPUSD"), "USD/JPY": ("frxUSDJPY", "USDJPY"),
    "Or": ("frxXAUUSD", "XAUUSD"),
}

mt5.initialize()
spread = {}
for name, (_, sym) in MARKETS.items():
    i = mt5.symbol_info(sym)
    spread[name] = i.spread * i.point          # spread en unités de prix
mt5.shutdown()

rows = []
for name, (code, _) in MARKETS.items():
    d1 = get_candles(code, "D1", 3000)
    for tf, secs, htfs, total in (("H1", 3600, ("W1", "D1", "H4"), 15000), ("M15", 900, ("W1", "D1", "H4", "H1"), 15000)):
        df = get_candles(code, tf, total)
        mp = replace(MTFParams(), entry_sec=secs, htfs=htfs, cost_price=spread[name])
        tr, _ = backtest_mtf(df, d1, mp)
        s = stats(tr)
        # coût du spread en R : spread / distance du stop (médiane)
        cost_R = round(float((spread[name] / (tr["entry"] - tr["init_sl"]).abs()).median()), 3) if not tr.empty else None
        rows.append({"marché": name, "entrée": tf, "jours": round((df.index[-1] - df.index[0]).days), **s, "spread_en_R": cost_R})
        print(rows[-1], flush=True)

res = pd.DataFrame(rows)
res.to_csv("tf_test.csv", index=False)
pd.set_option("display.width", 220)
print(res.to_string(index=False))
print("\n=== TOTAL avec le spread réel ===")
print(res.groupby("entrée").agg(trades=("trades", "sum"), total_R=("total_R", "sum"),
                               marchés_positifs=("total_R", lambda s: int((s > 0).sum()))).to_string())
