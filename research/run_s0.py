"""Stratégie ACTUELLE du bot (rebond sur lignes de tendance W1/D1/H4, entrée H1, stop suiveur),
rejouée telle quelle sur tout l'historique MT5 (jusqu'à 16 ans), avec le spread du broker et le portage (swap).
Les réglages ont été choisis sur nov. 2025 - nov. 2026 : tout ce qui précède est une période jamais vue.
Usage : python research/run_s0.py [symboles...]"""
import sys
import time
from dataclasses import replace
from multiprocessing import Pool
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent))
from lib import OUT, add_costs, fmt, fname, load, specs, table   # noqa: E402

# marché -> (symbole des données, symbole réellement tradé par le bot : ses coûts)
MARKETS = {"EUR/USD": ("EURUSD", "EURUSDmicro"), "GBP/USD": ("GBPUSD", "GBPUSDmicro"), "USD/JPY": ("USDJPY", "USDJPYmicro"),
           "USD/CAD": ("USDCAD", "USDCADmicro"), "USD/CHF": ("USDCHF", "USDCHFmicro"), "NZD/USD": ("NZDUSD", "NZDUSDmicro"),
           "AUD/USD": ("AUDUSD", "AUDUSDmicro"), "AUD/JPY": ("AUDJPY", "AUDJPY"), "EUR/AUD": ("EURAUD", "EURAUD"),
           "EUR/CAD": ("EURCAD", "EURCAD"), "EUR/CHF": ("EURCHF", "EURCHF"), "EUR/GBP": ("EURGBP", "EURGBP"),
           "EUR/JPY": ("EURJPY", "EURJPY"), "GBP/AUD": ("GBPAUD", "GBPAUD"), "GBP/JPY": ("GBPJPY", "GBPJPY"),
           "AUD/CAD": ("AUDCAD", "AUDCAD"), "AUD/CHF": ("AUDCHF", "AUDCHF"), "Or": ("XAUUSD", "XAUUSD"),
           "Volatility 10": ("Volatility 10 Index",) * 2, "Volatility 25": ("Volatility 25 Index",) * 2,
           "Volatility 50": ("Volatility 50 Index",) * 2, "Volatility 75": ("Volatility 75 Index",) * 2,
           "Volatility 100": ("Volatility 100 Index",) * 2, "Step Index": ("Step Index",) * 2}


def run(label: str):
    from mtf import MTFParams, backtest_mtf
    data, traded = MARKETS[label]
    cols = ["open", "high", "low", "close"]
    h1, d1 = load(data, "H1")[cols], load(data, "D1")[cols]
    t0 = time.time()
    tr, _ = backtest_mtf(h1, d1, replace(MTFParams(), cost_price=1e-12))      # brut : les coûts sont ajoutés ensuite
    if tr.empty:
        return label, tr
    tr = tr.rename(columns={"R": "R_gross"})
    tr["risk"] = (tr["entry"] - tr["init_sl"]).abs()
    tr["side"] = tr["side"].map({"long": 1, "short": -1})
    tr["marche"] = label
    tr = add_costs(tr, traded)
    tr["groupe"] = "synthétique" if "Index" in data else ("or" if data == "XAUUSD" else "forex")
    print(f"{label:16} {len(tr):5} trades  brut {tr.R_gross.mean():+.3f}  net {tr.R.mean():+.3f} R  ({time.time() - t0:.0f}s)", flush=True)
    return label, tr


if __name__ == "__main__":
    want = [a for a in sys.argv[1:]] or list(MARKETS)
    labels = [m for m in want if fname(MARKETS[m][0], "H1").exists() and MARKETS[m][1] in specs()]
    print("marchés :", ", ".join(labels), flush=True)
    with Pool(3) as pool:
        res = pool.map(run, labels)
    tr = pd.concat([t for _, t in res if len(t)])
    tr.to_pickle(OUT / "s0_trades.pkl")
    tr["annee"] = tr["entry_time"].dt.year
    print("\n=== Par année (R net, tous marchés) ===")
    print(fmt(table(tr, "annee")))
    print("\n=== Par marché ===")
    print(fmt(table(tr, "marche")))
    print("\n=== Par famille ===")
    print(fmt(table(tr, "groupe")))
    seen = tr[tr.entry_time < "2025-11-01"]
    print("\n=== Période jamais vue (avant nov. 2025) vs période de réglage ===")
    tr["periode"] = (tr.entry_time >= "2025-11-01").map({True: "réglage (nov. 2025+)", False: "jamais vue (avant)"})
    print(fmt(table(tr, ["groupe", "periode"])))
    print(f"\nCoût moyen : spread {tr.cost_R.mean():.3f} R, portage {-tr.swap_R.mean():.3f} R par trade ; durée moyenne {tr.bars.mean():.0f} h")
