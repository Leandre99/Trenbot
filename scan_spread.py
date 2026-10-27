"""Backtest H1 des 24 marchés avec le VRAI spread (lu dans MT5), avant et après le filtre de spread du bot."""
import MetaTrader5 as mt5
import pandas as pd
from dataclasses import replace

import config
from data import get_candles
from mtf import MTFParams, backtest_mtf
from strategy import stats

DERIV = {"Volatility 10": "R_10", "Volatility 25": "R_25", "Volatility 50": "R_50", "Volatility 75": "R_75",
         "Volatility 100": "R_100", "Step Index": "stpRNG", "Or": "frxXAUUSD",
         "EUR/USD": "frxEURUSD", "GBP/USD": "frxGBPUSD", "USD/JPY": "frxUSDJPY", "USD/CAD": "frxUSDCAD",
         "USD/CHF": "frxUSDCHF", "NZD/USD": "frxNZDUSD", "AUD/USD": "frxAUDUSD", "AUD/JPY": "frxAUDJPY",
         "EUR/AUD": "frxEURAUD", "EUR/CAD": "frxEURCAD", "EUR/CHF": "frxEURCHF", "EUR/GBP": "frxEURGBP",
         "EUR/JPY": "frxEURJPY", "GBP/AUD": "frxGBPAUD", "GBP/JPY": "frxGBPJPY", "AUD/CAD": "frxAUDCAD",
         "AUD/CHF": "frxAUDCHF"}

mt5.initialize()
avail = {s.name.lower(): s.name for s in mt5.symbols_get()}
spread = {}
for label in DERIV:
    real = next(avail[c.lower()] for c in config.SYMBOLS[label] if c.lower() in avail)
    i = mt5.symbol_info(real)
    spread[label] = (real, i.spread * i.point)
mt5.shutdown()

rows = []
for label, code in DERIV.items():
    real, sp = spread[label]
    h1, d1 = get_candles(code, "H1", 15000), get_candles(code, "D1", 3000)
    tr, _ = backtest_mtf(h1, d1, replace(MTFParams(), cost_price=sp))
    if tr.empty:
        continue
    cost_r = sp / (tr["entry"] - tr["init_sl"]).abs()
    kept = tr[cost_r <= config.MAX_SPREAD_R]
    s_all, s_kept = stats(tr), stats(kept)
    rows.append({"marché": label, "mt5": real, "spread_médian_en_R": round(float(cost_r.median()), 3),
                 "trades": s_all["trades"], "total_R_sans_filtre": s_all["total_R"],
                 "trades_gardés": s_kept.get("trades", 0), "total_R_avec_filtre": s_kept.get("total_R", 0)})
    print(rows[-1], flush=True)

df = pd.DataFrame(rows)
df.to_csv("scan_spread.csv", index=False)
pd.set_option("display.width", 220)
print(df.sort_values("spread_médian_en_R").to_string(index=False))
print(f"\nTOTAL sans filtre : {df['total_R_sans_filtre'].sum():+.1f} R ({df['trades'].sum()} trades)"
      f" | avec filtre (spread <= {config.MAX_SPREAD_R} R) : {df['total_R_avec_filtre'].sum():+.1f} R ({df['trades_gardés'].sum()} trades)")
