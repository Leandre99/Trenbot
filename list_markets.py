"""Liste tous les marchés de ton MT5 avec lot min, marge et risque d'un mouvement de 1 % (lecture seule)."""
import re
import sys

import MetaTrader5 as mt5
import pandas as pd

if not mt5.initialize():
    raise SystemExit(f"MT5 injoignable : {mt5.last_error()}")

rows = []
for s in mt5.symbols_get() or []:
    p = s.path.split("\\")
    group = "/".join(p[:-1])
    if not s.visible:
        mt5.symbol_select(s.name, True)
    i = mt5.symbol_info(s.name)
    tick = mt5.symbol_info_tick(s.name)
    price = (tick.ask if tick and tick.ask else i.bid) if i else 0
    if not price or i.trade_tick_size <= 0:
        continue
    tv = i.trade_tick_value_loss or i.trade_tick_value
    rows.append({"groupe": group, "symbole": s.name, "prix": round(price, i.digits), "lot_min": i.volume_min,
                 "spread": i.spread, "1%_mvt_$_lotmin": round(i.volume_min * price * 0.01 / i.trade_tick_size * tv, 2)})
mt5.shutdown()
df = pd.DataFrame(rows)
pat = sys.argv[1] if len(sys.argv) > 1 else ""
if pat:
    df = df[df["symbole"].str.contains(pat, case=False, regex=True) | df["groupe"].str.contains(pat, case=False, regex=True)]
pd.set_option("display.width", 250)
pd.set_option("display.max_rows", 500)
print(df.sort_values(["groupe", "symbole"]).to_string(index=False))
print("\nGroupes :", df["groupe"].value_counts().to_dict())
