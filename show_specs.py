"""Affiche les caractéristiques exactes de chaque marché chez ton broker (lecture seule, aucun ordre)."""
import MetaTrader5 as mt5
import pandas as pd

import config

if not mt5.initialize():
    raise SystemExit(f"MT5 injoignable : {mt5.last_error()}")
avail = {s.name.lower(): s.name for s in (mt5.symbols_get() or [])}
rows = []
for label, cands in config.SYMBOLS.items():
    real = next((avail[c.lower()] for c in cands if c.lower() in avail), None)
    if real is None:
        rows.append({"marché": label, "mt5": "INTROUVABLE"})
        continue
    mt5.symbol_select(real, True)
    i = mt5.symbol_info(real)
    tick = mt5.symbol_info_tick(real)
    price = tick.ask if tick and tick.ask else i.bid
    one_min = mt5.order_calc_margin(mt5.ORDER_TYPE_BUY, real, i.volume_min, price)
    # valeur d'un mouvement de 1 % du prix pour le lot minimum (donne une idée de la "taille" du lot min)
    pct1 = i.volume_min * price * 0.01 / i.trade_tick_size * (i.trade_tick_value_loss or i.trade_tick_value)
    rows.append({
        "marché": label, "mt5": real, "prix": round(price, i.digits),
        "taille contrat": i.trade_contract_size,
        "lot min": i.volume_min, "pas": i.volume_step, "lot max": i.volume_max,
        "valeur tick $": round(i.trade_tick_value, 4), "tick": i.trade_tick_size,
        "spread (pts)": i.spread, "stop mini (pts)": i.trade_stops_level,
        "marge lot min $": round(one_min, 2) if one_min is not None else None,
        "1 % de mvt = $ (lot min)": round(pct1, 2),
        "trading": {0: "désactivé", 1: "achat seul", 2: "vente seule", 3: "clôture seule", 4: "complet"}.get(i.trade_mode, i.trade_mode),
    })
mt5.shutdown()
pd.set_option("display.width", 300)
pd.set_option("display.max_columns", 30)
print(pd.DataFrame(rows).to_string(index=False))
