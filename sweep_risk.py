"""Effet du risque par trade et du nombre de positions simultanées sur le compte (mêmes trades, mêmes règles)."""
import pandas as pd

import config
from simulate_account import simulate, trades

t0, t1 = trades.entry_time.min(), trades.entry_time.max()
rows = []
for cap in (100, 500):
    for risk in (0.5, 1.0, 2.0):
        for maxpos in (2, 3, 5):
            config.RISK_PCT, config.MAX_POSITIONS = risk, maxpos
            y = simulate(cap)
            fin, dd, start = [], [], t0
            while start + pd.Timedelta(days=90) <= t1:
                w = simulate(cap, start, start + pd.Timedelta(days=90))
                fin.append(w["final"] / cap)
                dd.append(w["max_dd_pct"])
                start += pd.Timedelta(days=7)
            f = pd.Series(fin)
            rows.append({"capital": cap, "risque %": risk, "positions max": maxpos,
                         "année: gain %": round((y["final"] / cap - 1) * 100), "année: pire baisse %": round(y["max_dd_pct"]),
                         "3 mois: médiane %": round((f.median() - 1) * 100), "3 mois: pire 10 %": round((f.quantile(0.1) - 1) * 100),
                         "3 mois: gagnants %": round((f > 1).mean() * 100), "3 mois: baisse moy. %": round(sum(dd) / len(dd))})
config.RISK_PCT, config.MAX_POSITIONS = 1.0, 3
pd.set_option("display.width", 250)
print(pd.DataFrame(rows).to_string(index=False))
