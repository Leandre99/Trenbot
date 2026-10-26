"""Compare l'entrée actuelle (rebond direct) et l'entrée en deux temps (retour après cassure)."""
import sys
from dataclasses import replace

import pandas as pd

from data import SYMBOLS, get_candles
from mtf import MTFParams, backtest_mtf
from strategy import stats

base = MTFParams()
variants = {
    "A_rebond_direct": base,
    "B_deux_temps_0.5": replace(base, entry_mode="reclaim", reclaim_depth=0.5),
    "B_deux_temps_1.0": replace(base, entry_mode="reclaim", reclaim_depth=1.0),
}

rows = []
for name, code in SYMBOLS.items():
    h1, d1 = get_candles(code, "H1", 15000), get_candles(code, "D1", 3000)
    cache = {}  # les lignes sont les mêmes pour toutes les variantes : on ne les recalcule pas
    for vname, mp in variants.items():
        tr, cache = backtest_mtf(h1, d1, mp, cache)
        rows.append({"marché": name, "variante": vname, **stats(tr)})
    print(name, "ok", flush=True)

df = pd.DataFrame(rows)
df.to_csv("compare_entries.csv", index=False)
pd.set_option("display.width", 220)
print(df.to_string(index=False))

print("\n=== TOTAL sur les 10 marchés (en R : 1 R = le risque pris sur chaque trade) ===")
g = df.groupby("variante").agg(trades=("trades", "sum"), total_R=("total_R", "sum"),
                               marchés_positifs=("total_R", lambda s: int((s > 0).sum())),
                               maxDD_R_pire=("maxDD_R", "max"))
g["R_par_trade"] = (g["total_R"] / g["trades"]).round(3)
print(g.to_string())
