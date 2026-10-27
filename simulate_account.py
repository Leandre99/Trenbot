"""Simule un compte avec les VRAIES règles du bot, sur les trades du backtest H1 (spreads et lots réels de ton broker).

Règles reprises de config.py / live_mt5.py : risque 1 % par trade (lot minimum accepté jusqu'à 3 %), config.MAX_POSITIONS positions max,
une seule par marché, filtre de spread 0,15 R, marge <= 50 % de la marge libre, arrêt du jour à -3 %.
Usage : python simulate_account.py
"""
import json
from collections import Counter

import numpy as np
import pandas as pd

import config
from risk import daily_halt, lot_for_risk, spread_cost_r

specs = json.load(open("sim_specs.json"))
trades = pd.read_csv("sim_trades.csv", parse_dates=["entry_time", "exit_time"])


def simulate(capital: float, start=None, end=None):
    tr = trades if start is None else trades[(trades.entry_time >= start) & (trades.entry_time < end)]
    equity, day, day_start = capital, None, capital
    open_pos, refused, taken = [], Counter(), []
    peak, max_dd, curve = capital, 0.0, [(tr.entry_time.min() if len(tr) else None, capital)]

    def close_until(t):
        nonlocal equity, peak, max_dd
        open_pos.sort(key=lambda p: p["exit"])
        while open_pos and open_pos[0]["exit"] <= t:
            p = open_pos.pop(0)
            equity += p["pnl"]
            peak = max(peak, equity)
            max_dd = max(max_dd, (peak - equity) / peak * 100 if peak > 0 else 100)
            curve.append((p["exit"], equity))

    for r in tr.itertuples():
        close_until(r.entry_time)
        if equity <= 0:
            refused["compte épuisé"] += 1
            continue
        if r.entry_time.date() != day:
            day, day_start = r.entry_time.date(), equity
        if len(open_pos) >= config.MAX_POSITIONS:
            refused[f"{config.MAX_POSITIONS} positions déjà ouvertes"] += 1
            continue
        if daily_halt(equity, day_start, config.DAILY_LOSS_STOP_PCT):
            refused["arrêt du jour (-3 %)"] += 1
            continue
        s = specs[r.marche]
        if spread_cost_r(s["spread"], r.entry, r.init_sl) > config.MAX_SPREAD_R:
            refused["spread trop large"] += 1
            continue
        lots = lot_for_risk(equity, config.RISK_PCT, config.MAX_RISK_PCT, r.entry, r.init_sl, s["tick_size"],
                            s["tick_value"], s["vol_min"], s["vol_max"], s["vol_step"])
        if lots.reason:
            refused["lot minimum trop gros"] += 1
            continue
        margin = lots.lots * s["margin_per_lot"] * (r.entry / s["price_now"])
        free = equity - sum(p["margin"] for p in open_pos)
        if margin > free * config.MAX_MARGIN_PCT / 100:
            refused["marge insuffisante"] += 1
            continue
        pnl = r.R * lots.risk_money
        open_pos.append({"exit": r.exit_time, "pnl": pnl, "margin": margin})
        taken.append({"marche": r.marche, "R": r.R, "pnl": pnl, "risk": lots.risk_money, "lots": lots.lots})
    close_until(pd.Timestamp.max)
    t = pd.DataFrame(taken)
    return {"final": equity, "max_dd_pct": max_dd, "taken": len(t), "refused": refused,
            "wins": float((t.pnl > 0).mean() * 100) if len(t) else 0.0, "detail": t, "curve": curve,
            "n_signals": len(tr)}


if __name__ == "__main__":
    t0, t1 = trades.entry_time.min(), trades.entry_time.max()
    days = (t1 - t0).days
    print(f"Trades du backtest : {len(trades)} sur {days} jours ({t0.date()} -> {t1.date()}), 24 marchés\n")

    print("=== 1. L'année complète avec les vraies règles ===")
    rows = []
    for cap in (100, 250, 500, 1000):
        r = simulate(cap)
        rows.append({"capital départ": cap, "capital final": round(r["final"], 1),
                     "gain %": round((r["final"] / cap - 1) * 100, 1), "pire baisse %": round(r["max_dd_pct"], 1),
                     "trades pris": r["taken"], "sur signaux": r["n_signals"], "gagnants %": round(r["wins"], 1)})
    print(pd.DataFrame(rows).to_string(index=False))

    r = simulate(100)
    print("\n=== 2. Pourquoi des signaux sont refusés à 100 $ ===")
    for k, v in r["refused"].most_common():
        print(f"  {k:30} {v:5}  ({v / r['n_signals'] * 100:.0f} % des signaux)")
    print(f"  {'trades réellement pris':30} {r['taken']:5}  ({r['taken'] / r['n_signals'] * 100:.0f} % des signaux)")

    print("\n=== 3. Marchés réellement tradés à 100 $ ===")
    d = r["detail"]
    g = d.groupby("marche").agg(trades=("pnl", "size"), gain_dollars=("pnl", "sum"), risque_moyen=("risk", "mean"))
    print(g.round(2).sort_values("trades", ascending=False).to_string())

    print("\n=== 4. Ce qu'on peut attendre sur 3 mois (fenêtres glissantes de 90 jours, départ à 100 $) ===")
    res = []
    start = t0
    while start + pd.Timedelta(days=90) <= t1:
        w = simulate(100, start, start + pd.Timedelta(days=90))
        res.append({"debut": start.date(), "final": w["final"], "dd": w["max_dd_pct"], "taken": w["taken"]})
        start += pd.Timedelta(days=7)
    w = pd.DataFrame(res)
    print(f"  {len(w)} fenêtres (elles se chevauchent : ce n'est PAS {len(w)} essais indépendants)")
    for lab, q in (("pire 10 %", 0.10), ("médiane", 0.50), ("meilleur 10 %", 0.90)):
        print(f"  {lab:14}: capital final {w.final.quantile(q):7.1f} $")
    print(f"  fenêtres gagnantes : {(w.final > 100).mean() * 100:.0f} %   |   finissant sous 50 $ : {(w.final < 50).mean() * 100:.0f} %"
          f"   |   pire baisse moyenne : {w.dd.mean():.0f} %, pire cas : {w.dd.max():.0f} %")
    print(f"  trades pris par fenêtre : {w.taken.mean():.0f} en moyenne")
    w.to_csv("sim_windows.csv", index=False)
