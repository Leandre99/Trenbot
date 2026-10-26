import pandas as pd

from data import SYMBOLS, get_candles
from mtf import MTFParams, backtest_mtf
from strategy import stats

rows = []
for name, sym in SYMBOLS.items():
    try:
        h1 = get_candles(sym, "H1", 15000)
        d1 = get_candles(sym, "D1", 3000)
    except Exception as e:
        print(f"{name}: échec données ({e})")
        continue
    tr, _ = backtest_mtf(h1, d1, MTFParams())
    if not tr.empty:
        tr.to_csv(f"mtf_trades_{sym}.csv", index=False)
    s = stats(tr.rename(columns={})) if not tr.empty else {"trades": 0}
    rows.append({"symbole": name, "de": h1.index[0].date(), "à": h1.index[-1].date(), **s})

pd.set_option("display.width", 200)
print(pd.DataFrame(rows).to_string(index=False))
