"""Deux améliorations testées sur les 24 marchés, spreads réels, filtre de spread du bot appliqué :
  - filtre de tendance de fond (D1 au-dessus / en dessous de sa moyenne 50)
  - stop ramené à l'entrée quand le gain latent atteint 1 R (break-even)
On regarde aussi chaque moitié de l'année : une amélioration utile doit aider dans les deux."""
from dataclasses import replace

import MetaTrader5 as mt5
import pandas as pd

import config
from data import get_candles
from mtf import MTFParams, backtest_mtf

DERIV = {"Volatility 10": "R_10", "Volatility 25": "R_25", "Volatility 50": "R_50", "Volatility 75": "R_75",
         "Volatility 100": "R_100", "Step Index": "stpRNG", "Or": "frxXAUUSD",
         "EUR/USD": "frxEURUSD", "GBP/USD": "frxGBPUSD", "USD/JPY": "frxUSDJPY", "USD/CAD": "frxUSDCAD",
         "USD/CHF": "frxUSDCHF", "NZD/USD": "frxNZDUSD", "AUD/USD": "frxAUDUSD", "AUD/JPY": "frxAUDJPY",
         "EUR/AUD": "frxEURAUD", "EUR/CAD": "frxEURCAD", "EUR/CHF": "frxEURCHF", "EUR/GBP": "frxEURGBP",
         "EUR/JPY": "frxEURJPY", "GBP/AUD": "frxGBPAUD", "GBP/JPY": "frxGBPJPY", "AUD/CAD": "frxAUDCAD",
         "AUD/CHF": "frxAUDCHF"}
VARIANTS = {
    "0_actuel": {},
    "1_tendance_de_fond": {"trend_filter": True},
    "2_break_even_1R": {"be_r": 1.0},
    "3_tendance+break_even": {"trend_filter": True, "be_r": 1.0},
}

mt5.initialize()
avail = {s.name.lower(): s.name for s in mt5.symbols_get()}
spread = {}
for label in DERIV:
    real = next(avail[c.lower()] for c in config.SYMBOLS[label] if c.lower() in avail)
    i = mt5.symbol_info(real)
    spread[label] = i.spread * i.point
mt5.shutdown()

allt = []
for label, code in DERIV.items():
    h1, d1 = get_candles(code, "H1", 15000), get_candles(code, "D1", 3000)
    cache = {}
    for vname, kw in VARIANTS.items():
        tr, cache = backtest_mtf(h1, d1, replace(MTFParams(), cost_price=spread[label], **kw), cache)
        if tr.empty:
            continue
        cost_r = spread[label] / (tr["entry"] - tr["init_sl"]).abs()
        tr = tr[cost_r <= config.MAX_SPREAD_R].copy()      # le filtre de spread du bot
        tr["variante"], tr["marche"], tr["mid"] = vname, label, h1.index[len(h1) // 2]
        allt.append(tr[["variante", "marche", "R", "entry_time", "mid"]])
    print(label, "ok", flush=True)

df = pd.concat(allt)
df["moitie"] = (df["entry_time"] >= df["mid"]).map({False: "1re", True: "2e"})
res = df.groupby("variante").agg(trades=("R", "size"), total_R=("R", "sum"), R_par_trade=("R", "mean"),
                                 gagnants_pct=("R", lambda s: (s > 0).mean() * 100))
res["total_R_1re_moitie"] = df[df.moitie == "1re"].groupby("variante")["R"].sum()
res["total_R_2e_moitie"] = df[df.moitie == "2e"].groupby("variante")["R"].sum()
res["marches_positifs"] = df.groupby(["variante", "marche"])["R"].sum().groupby("variante").apply(lambda s: int((s > 0).sum()))
# pire série de pertes (en R, trades classés par date, tous marchés confondus)
res["pire_baisse_R"] = df.sort_values("entry_time").groupby("variante")["R"].apply(
    lambda s: float((s.cumsum().cummax() - s.cumsum()).max()))
pd.set_option("display.width", 220)
print(res.round(3).to_string())
df.to_csv("improve_test_trades.csv", index=False)
