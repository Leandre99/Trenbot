"""Backtest de la stratégie sur d'autres marchés (forex majeurs/mineurs, Boom/Crash). Données publiques Deriv."""
import pandas as pd

from data import get_candles
from mtf import MTFParams, backtest_mtf
from strategy import stats

MARKETS = {
    "AUD/JPY": "frxAUDJPY", "AUD/USD": "frxAUDUSD", "EUR/AUD": "frxEURAUD", "EUR/CAD": "frxEURCAD",
    "EUR/CHF": "frxEURCHF", "EUR/GBP": "frxEURGBP", "EUR/JPY": "frxEURJPY", "GBP/AUD": "frxGBPAUD",
    "GBP/JPY": "frxGBPJPY", "USD/CAD": "frxUSDCAD", "USD/CHF": "frxUSDCHF", "NZD/USD": "frxNZDUSD",
    "AUD/CAD": "frxAUDCAD", "AUD/CHF": "frxAUDCHF",
    "Boom 1000": "BOOM1000", "Boom 500": "BOOM500", "Boom 300": "BOOM300N",
    "Crash 1000": "CRASH1000", "Crash 500": "CRASH500", "Crash 300": "CRASH300N",
}

rows = []
for name, code in MARKETS.items():
    try:
        h1, d1 = get_candles(code, "H1", 15000), get_candles(code, "D1", 3000)
    except Exception as e:
        rows.append({"marché": name, "note": f"données indisponibles ({str(e)[:40]})"})
        print(rows[-1], flush=True)
        continue
    tr, _ = backtest_mtf(h1, d1, MTFParams())
    rows.append({"marché": name, **stats(tr)})
    print(rows[-1], flush=True)

df = pd.DataFrame(rows)
df.to_csv("scan_new_results.csv", index=False)
pd.set_option("display.width", 200)
print("\n", df.sort_values("total_R", ascending=False).to_string(index=False))
