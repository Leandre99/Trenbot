"""Bilan du bot depuis MT5 : trades fermés, gain/perte, taux de réussite, par marché.

Usage : python report.py [jours]        (défaut : 30 derniers jours ; MT5 ouvert, lecture seule)
"""
import sys
from datetime import datetime, timedelta, timezone

import MetaTrader5 as mt5
import pandas as pd

import config

days = int(sys.argv[1]) if len(sys.argv) > 1 else 30
if not mt5.initialize():
    raise SystemExit(f"MT5 injoignable : {mt5.last_error()}")
now = datetime.now(timezone.utc)
deals = [d for d in (mt5.history_deals_get(now - timedelta(days=days), now + timedelta(days=1)) or [])
         if d.magic == config.MAGIC]
open_pos = [p for p in (mt5.positions_get() or []) if p.magic == config.MAGIC]
mt5.shutdown()

if not deals and not open_pos:
    raise SystemExit(f"Aucun trade du bot (magic {config.MAGIC}) sur les {days} derniers jours.")

rows = {}
for d in deals:
    r = rows.setdefault(d.position_id, {"marche": d.symbol, "net": 0.0, "ouvert": None, "ferme": None, "sorties": 0})
    r["net"] += d.profit + d.commission + d.swap + d.fee
    t = datetime.fromtimestamp(d.time, timezone.utc)
    if d.entry == mt5.DEAL_ENTRY_IN:
        r["ouvert"] = t
    elif d.entry in (mt5.DEAL_ENTRY_OUT, mt5.DEAL_ENTRY_OUT_BY):
        r["ferme"] = t
        r["sorties"] += 1
df = pd.DataFrame(rows.values())
closed = df[df["sorties"] > 0] if not df.empty else df

pd.set_option("display.width", 200)
if not closed.empty:
    wins, losses = closed[closed["net"] > 0]["net"], closed[closed["net"] <= 0]["net"]
    print(f"\nTrades fermés : {len(closed)} | gagnants : {len(wins)} ({len(wins) / len(closed) * 100:.0f} %) | "
          f"résultat net : {closed['net'].sum():+.2f} $")
    if len(wins) and len(losses):
        print(f"Gain moyen : {wins.mean():+.2f} $ | perte moyenne : {losses.mean():+.2f} $ | "
              f"facteur de gain : {wins.sum() / -losses.sum():.2f}")
    print("\nPar marché :")
    print(closed.groupby("marche")["net"].agg(trades="size", net="sum").round(2).sort_values("net").to_string())
else:
    print("\nAucun trade fermé pour l'instant.")
print(f"\nPositions encore ouvertes : {len(open_pos)}")
for p in open_pos:
    print(f"  {p.symbol:22} {'ACHAT' if p.type == mt5.POSITION_TYPE_BUY else 'VENTE':5} {p.volume} lot | "
          f"stop {p.sl} | latent {p.profit + p.swap:+.2f} $")
