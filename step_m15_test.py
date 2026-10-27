"""Step Index en M15 : test sérieux (1 an+, trimestres, robustesse des réglages, spread doublé, lot à 100 $)."""
from dataclasses import replace

import MetaTrader5 as mt5
import pandas as pd

from data import get_candles
from mtf import MTFParams, backtest_mtf
from strategy import stats

mt5.initialize()
info = mt5.symbol_info("Step Index")
spread = info.spread * info.point
tick_size, tick_val, lot_min = info.trade_tick_size, info.trade_tick_value, info.volume_min
mt5.shutdown()
print(f"Step Index : spread={spread}, tick={tick_size}, valeur tick={tick_val}, lot min={lot_min}", flush=True)

m15 = get_candles("stpRNG", "M15", 40000)
d1 = get_candles("stpRNG", "D1", 3000)
print(f"M15 : {len(m15)} bougies, du {m15.index[0].date()} au {m15.index[-1].date()} "
      f"({(m15.index[-1] - m15.index[0]).days} jours)", flush=True)

base = replace(MTFParams(), entry_sec=900, htfs=("W1", "D1", "H4", "H1"), cost_price=spread)
tr, cache = backtest_mtf(m15, d1, base)            # `cache` : lignes réutilisées pour toutes les variantes
print("\n=== 1. Test complet ===")
print(stats(tr), flush=True)

print("\n=== 2. Par trimestre (régularité) ===")
tr["trimestre"] = pd.PeriodIndex(tr["entry_time"], freq="Q").astype(str)
q = tr.groupby("trimestre").agg(trades=("R", "size"), total_R=("R", "sum"), win=("R", lambda s: round((s > 0).mean() * 100, 1)))
q["total_R"] = q["total_R"].round(1)
print(q.to_string(), flush=True)

print("\n=== 3. Robustesse : on change UN réglage à la fois ===")
rows = []
for param, values in (("touch_atr", [0.15, 0.3, 0.5]), ("sl_atr", [0.5, 1.0, 1.5, 2.0]),
                      ("pivot_n", [2, 3, 5]), ("trail_atr", [0.1, 0.25, 0.5])):
    for v in values:
        t, _ = backtest_mtf(m15, d1, replace(base, **{param: v}), cache)
        rows.append({"réglage": f"{param}={v}" + (" (défaut)" if getattr(base, param) == v else ""), **stats(t)})
        print(rows[-1], flush=True)
print(pd.DataFrame(rows).to_string(index=False), flush=True)

print("\n=== 4. Spread x2 et x3 (il peut s'élargir) ===")
for k in (2, 3):
    t, _ = backtest_mtf(m15, d1, replace(base, cost_price=spread * k), cache)
    print(f"spread x{k}:", stats(t), flush=True)

print("\n=== 5. Référence : H1 sur la même période ===")
h1 = get_candles("stpRNG", "H1", 15000)
t, _ = backtest_mtf(h1, d1, replace(MTFParams(), cost_price=spread))
print("H1 :", stats(t), flush=True)

print("\n=== 6. Lot minimum à 100 $ ===")
dist = (tr["entry"] - tr["init_sl"]).abs()
for name, q_ in (("stop typique (médiane)", 0.5), ("stop large (90 %)", 0.9), ("stop petit (25 %)", 0.25)):
    d = float(dist.quantile(q_))
    risk = lot_min * d / tick_size * tick_val
    print(f"{name:24} distance={d:6.2f} -> perte au lot min ({lot_min}) = {risk:6.2f} $  "
          f"= {risk:.1f} % de 100 $ | capital pour que ce soit 3 % : {risk / 0.03:6.0f} $ | pour 1 % : {risk / 0.01:6.0f} $")
tr.to_csv("step_m15_trades.csv", index=False)
