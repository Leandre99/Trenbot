import sys

import pandas as pd

from data import SYMBOLS, get_candles
from strategy import Params, backtest, stats

tf = sys.argv[1] if len(sys.argv) > 1 else "H1"
total = int(sys.argv[2]) if len(sys.argv) > 2 else 20000
cost = float(sys.argv[3]) if len(sys.argv) > 3 else 0.05  # spread approx., en ATR

rows = []
for name, sym in SYMBOLS.items():
    try:
        df = get_candles(sym, tf, total)
    except Exception as e:
        print(f"{name}: échec données ({e})")
        continue
    # Séparation in-sample / out-of-sample (70/30) pour éviter de se tromper soi-même
    cut = int(len(df) * 0.7)
    for label, part in (("train", df.iloc[:cut]), ("test", df.iloc[cut:])):
        tr = backtest(part, Params(cost_atr=cost))
        rows.append({"symbole": name, "période": label, "bougies": len(part), **stats(tr)})
        if label == "test" and not tr.empty:
            tr.to_csv(f"trades_{sym}_{tf}.csv", index=False)

res = pd.DataFrame(rows)
pd.set_option("display.width", 200)
print(res.to_string(index=False))
