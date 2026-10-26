"""Affiche, pour un capital donné, les lots et le risque réel en $ de chaque marché.

Usage : python show_risk.py [capital]      (MT5 ouvert ; aucun ordre n'est envoyé)
Le stop « typique » est mesuré sur le backtest (médiane des distances entrée -> stop initial).
"""
import sys

import MetaTrader5 as mt5
import pandas as pd

import config
from data import get_candles
from mtf import MTFParams, backtest_mtf
from risk import lot_for_risk

capital = float(sys.argv[1]) if len(sys.argv) > 1 else 100.0
DERIV = {"Volatility 10": "R_10", "Volatility 25": "R_25", "Volatility 50": "R_50", "Volatility 75": "R_75",
         "Volatility 100": "R_100", "Step Index": "stpRNG", "EUR/USD": "frxEURUSD", "GBP/USD": "frxGBPUSD",
         "USD/JPY": "frxUSDJPY", "Or": "frxXAUUSD"}

if not mt5.initialize():
    raise SystemExit(f"MT5 injoignable : {mt5.last_error()}")
avail = {s.name.lower(): s.name for s in (mt5.symbols_get() or [])}

rows = []
for label, dsym in DERIV.items():
    real = next((avail[c.lower()] for c in config.SYMBOLS[label] if c.lower() in avail), None)
    if real is None:
        rows.append({"marché": label, "note": "introuvable chez ce broker"})
        continue
    h1, d1 = get_candles(dsym, "H1", 15000), get_candles(dsym, "D1", 3000)
    tr, _ = backtest_mtf(h1, d1, MTFParams())
    if tr.empty:
        rows.append({"marché": label, "note": "aucun trade au backtest"})
        continue
    dist = (tr["entry"] - tr["init_sl"]).abs()
    info = mt5.symbol_info(real)
    tv = info.trade_tick_value_loss if info.trade_tick_value_loss > 0 else info.trade_tick_value
    entry = float(tr["entry"].median())
    out = {"marché": label, "mt5": real, "lot_min": info.volume_min, "pas": info.volume_step}
    for tag, q in (("stop typique", 0.5), ("stop large", 0.9)):
        d = float(dist.quantile(q))
        r = lot_for_risk(capital, config.RISK_PCT, config.MAX_RISK_PCT, entry, entry - d,
                         info.trade_tick_size, tv, info.volume_min, info.volume_max, info.volume_step)
        loss_min = info.volume_min * d / info.trade_tick_size * tv   # perte au stop avec le lot minimum
        out[f"{tag}: lots"] = r.lots if not r.reason else "REFUSÉ"
        out[f"{tag}: risque $"] = round(r.risk_money, 2)
        out[f"{tag}: lot min coûterait $"] = round(loss_min, 2)
        if tag == "stop typique":
            m = mt5.order_calc_margin(mt5.ORDER_TYPE_BUY, real, r.lots or info.volume_min, entry)
            out["marge requise $ (lot pris ou lot min)"] = round(m, 2) if m is not None else None
    rows.append(out)
mt5.shutdown()

pd.set_option("display.width", 250)
pd.set_option("display.max_columns", 30)
print(f"\nCapital simulé : {capital:.0f} $ | risque visé {config.RISK_PCT} % = {capital * config.RISK_PCT / 100:.2f} $ "
      f"| refus si lot min > {config.MAX_RISK_PCT} % = {capital * config.MAX_RISK_PCT / 100:.2f} $\n")
print(pd.DataFrame(rows).to_string(index=False))
