"""Garder seulement les marchés positifs : est-ce que ça marche vraiment ?
On choisit les marchés avec la 1re moitié de l'année, puis on regarde ce qu'ils font sur la 2e moitié."""
import pandas as pd

from data import get_candles
from mtf import MTFParams, backtest_mtf

MARKETS = {
    "Volatility 10": "R_10", "Volatility 25": "R_25", "Volatility 50": "R_50", "Volatility 75": "R_75",
    "Volatility 100": "R_100", "Step Index": "stpRNG", "EUR/USD": "frxEURUSD", "GBP/USD": "frxGBPUSD",
    "USD/JPY": "frxUSDJPY", "Or": "frxXAUUSD",
    "AUD/JPY": "frxAUDJPY", "AUD/USD": "frxAUDUSD", "EUR/AUD": "frxEURAUD", "EUR/CAD": "frxEURCAD",
    "EUR/CHF": "frxEURCHF", "EUR/GBP": "frxEURGBP", "EUR/JPY": "frxEURJPY", "GBP/AUD": "frxGBPAUD",
    "GBP/JPY": "frxGBPJPY", "USD/CAD": "frxUSDCAD", "USD/CHF": "frxUSDCHF", "NZD/USD": "frxNZDUSD",
    "AUD/CAD": "frxAUDCAD", "AUD/CHF": "frxAUDCHF",
}

rows = []
for name, code in MARKETS.items():
    h1, d1 = get_candles(code, "H1", 15000), get_candles(code, "D1", 3000)
    cut = h1.index[len(h1) // 2]
    out = {"marché": name}
    for label, part in (("R_1re_moitié", h1[h1.index < cut]), ("R_2e_moitié", h1[h1.index >= cut])):
        tr, _ = backtest_mtf(part, d1, MTFParams())
        out[label] = round(tr["R"].sum(), 1) if not tr.empty else 0.0
        out["n_" + label[-6:]] = len(tr)
    rows.append(out)
    print(out, flush=True)

df = pd.DataFrame(rows)
df.to_csv("split_check.csv", index=False)
pd.set_option("display.width", 200)
print(df.to_string(index=False))

pos = df[df["R_1re_moitié"] > 0]
print(f"\nTous les marchés ({len(df)}) : 2e moitié = {df['R_2e_moitié'].sum():+.1f} R "
      f"({(df['R_2e_moitié'] > 0).sum()} positifs)")
print(f"Marchés positifs en 1re moitié ({len(pos)}) : 2e moitié = {pos['R_2e_moitié'].sum():+.1f} R "
      f"({(pos['R_2e_moitié'] > 0).sum()} restent positifs)")
neg = df[df["R_1re_moitié"] <= 0]
print(f"Marchés négatifs en 1re moitié ({len(neg)}) : 2e moitié = {neg['R_2e_moitié'].sum():+.1f} R "
      f"({(neg['R_2e_moitié'] > 0).sum()} deviennent positifs)")
