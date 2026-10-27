"""Prépare la simulation de compte : tous les trades du backtest H1 (24 marchés, spreads réels)
+ les caractéristiques exactes de chaque marché chez ton broker (lot min, valeur du tick, marge...).
Sorties : sim_trades.csv, sim_specs.json."""
import json
from dataclasses import replace

import MetaTrader5 as mt5
import pandas as pd

import config
from data import get_candles
from mtf import MTFParams, backtest_mtf

DERIV = {"Volatility 10": "R_10", "Volatility 25": "R_25", "Volatility 50": "R_50", "Volatility 75": "R_75",
         "Volatility 100": "R_100", "Step Index": "stpRNG", "Or": "frxXAUUSD",
         "EUR/USD": "frxEURUSD", "GBP/USD": "frxGBPUSD", "USD/JPY": "frxUSDJPY", "USD/CAD": "frxUSDCAD",
         "USD/CHF": "frxUSDCHF", "NZD/USD": "frxNZDUSD", "AUD/USD": "frxAUDUSD", "AUD/JPY": "frxAUDJPY",
         "EUR/AUD": "frxEURAUD", "EUR/CAD": "frxEURCAD", "EUR/CHF": "frxEURCHF", "EUR/GBP": "frxEURGBP",
         "EUR/JPY": "frxEURJPY", "GBP/AUD": "frxGBPAUD", "GBP/JPY": "frxGBPJPY", "AUD/CAD": "frxAUDCAD",
         "AUD/CHF": "frxAUDCHF"}

mt5.initialize()
avail = {s.name.lower(): s.name for s in mt5.symbols_get()}
specs = {}
for label in DERIV:
    real = next(avail[c.lower()] for c in config.SYMBOLS[label] if c.lower() in avail)
    mt5.symbol_select(real, True)
    i, tick = mt5.symbol_info(real), mt5.symbol_info_tick(real)
    price = tick.ask or i.bid
    margin_lot = mt5.order_calc_margin(mt5.ORDER_TYPE_BUY, real, 1.0, price)
    specs[label] = {"mt5": real, "spread": i.spread * i.point, "tick_size": i.trade_tick_size,
                    "tick_value": i.trade_tick_value_loss or i.trade_tick_value, "vol_min": i.volume_min,
                    "vol_max": i.volume_max, "vol_step": i.volume_step, "price_now": price,
                    "margin_per_lot": margin_lot}
mt5.shutdown()
json.dump(specs, open("sim_specs.json", "w"), indent=1)

rows = []
for order, (label, code) in enumerate(DERIV.items()):
    h1, d1 = get_candles(code, "H1", 15000), get_candles(code, "D1", 3000)
    tr, _ = backtest_mtf(h1, d1, replace(MTFParams(), cost_price=specs[label]["spread"]))
    tr["marche"], tr["ordre"] = label, order
    rows.append(tr[["marche", "ordre", "side", "entry_time", "exit_time", "entry", "exit", "init_sl", "R", "bars"]])
    print(label, len(tr), "trades", flush=True)
pd.concat(rows).sort_values(["entry_time", "ordre"]).to_csv("sim_trades.csv", index=False)
print("sim_trades.csv et sim_specs.json écrits")
