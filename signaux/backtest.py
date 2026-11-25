"""Backtest de la stratégie de signaux.py sur l'historique Deriv (API publique, rien n'est envoyé).

Rejoue detect() bougie par bougie, exactement comme en direct (fenêtre des 200 dernières bougies terminées),
puis compare plusieurs façons de placer le SL et le TP sur les MÊMES signaux.

    python backtest.py                    # tous les marchés, M15 M30 H1 H4, 5000 bougies chacun
    python backtest.py --bougies 2000     # plus court
    python backtest.py --unites H1 H4

Hypothèses (à garder en tête) :
  - entrée au prix de clôture de la bougie du signal ;
  - si SL et TP sont touchés dans la même bougie, on compte une PERTE (prudent) ;
  - trade non résolu à la fin des données : ignoré ;
  - spread et commissions NON comptés (ils réduisent les résultats, surtout pour les SL serrés).
"""
import argparse
import asyncio
import json
import time
from pathlib import Path

import numpy as np
import pandas as pd
import websockets

import signaux as s

FENETRE = s.NB_BOUGIES          # le bot en direct analyse les 200 dernières bougies


async def fetch(reqs: list[tuple[str, int]], count: int) -> dict:
    out = {}
    async with websockets.connect(s.WS_URL, open_timeout=20, close_timeout=5, max_size=2 ** 24) as ws:
        for n, (code, g) in enumerate(reqs, start=1):
            await ws.send(json.dumps({"ticks_history": code, "adjust_start_time": 1, "count": count, "end": "latest",
                                      "granularity": g, "style": "candles", "req_id": n}))
            while True:
                resp = json.loads(await asyncio.wait_for(ws.recv(), 60))
                if resp.get("req_id") == n:
                    break
            if "error" in resp:
                print(f"  {code} {g}s : {resp['error'].get('message')}")
                continue
            out[(code, g)] = resp.get("candles", [])
    return out


def atr(df: pd.DataFrame, n: int = 14) -> pd.Series:
    return s.atr(df, n)


def variantes(df: pd.DataFrame, i: int, side: int, entry: float, a: float) -> dict:
    """SL / TP de chaque variante pour un signal sur la bougie i. None si la variante est impossible."""
    out = {}
    for nb in (10, 5):
        lows, highs = df["low"].iloc[i - nb + 1:i + 1], df["high"].iloc[i - nb + 1:i + 1]
        sl = float(lows.min()) if side > 0 else float(highs.max())
        risk = (entry - sl) * side
        for r in (1.0, 1.5, 2.0, 3.0):
            out[f"SL {nb} bougies, TP {r:g}R"] = (sl, entry + side * r * risk) if risk > 0 else None
    for k_sl, k_tp in ((1.5, 1.5), (1.5, 3.0), (2.0, 2.0), (2.0, 4.0)):
        out[f"SL {k_sl:g} ATR, TP {k_tp:g} ATR"] = (entry - side * k_sl * a, entry + side * k_tp * a)
    return out


def issue(df: pd.DataFrame, i: int, side: int, entry: float, sl: float, tp: float) -> float | None:
    """Résultat en R (TP = +gain/risque, SL = -1), ou None si non résolu."""
    risk = (entry - sl) * side
    hi, lo = df["high"].to_numpy(), df["low"].to_numpy()
    for j in range(i + 1, len(df)):
        hit_sl = lo[j] <= sl if side > 0 else hi[j] >= sl
        hit_tp = hi[j] >= tp if side > 0 else lo[j] <= tp
        if hit_sl:
            return -1.0
        if hit_tp:
            return (tp - entry) * side / risk
    return None


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--bougies", type=int, default=5000, help="bougies d'historique par marché et unité (max 5000)")
    ap.add_argument("--unites", nargs="*", default=None)
    args = ap.parse_args()
    cfg = dict(s.DEFAULT)
    if s.CONFIG.exists():
        cfg.update(json.loads(s.CONFIG.read_text(encoding="utf-8")))
    unites = args.unites or cfg["unites"]
    reqs = [(code, s.GRAN[tf]) for tf in unites for code in cfg["marches"].values()]
    print(f"Téléchargement : {len(cfg['marches'])} marchés x {unites} x {args.bougies} bougies ...")
    t0 = time.time()
    data = asyncio.run(fetch(reqs, args.bougies))
    print(f"  fait en {time.time() - t0:.0f} s")

    rows = []
    for tf in unites:
        g = s.GRAN[tf]
        for name, code in cfg["marches"].items():
            raw = data.get((code, g))
            if not raw:
                continue
            df = s.candles(raw, g, time.time())
            a14 = atr(df)
            first = None
            for i in range(FENETRE, len(df)):
                sig = s.detect(df.iloc[i - FENETRE + 1:i + 1].reset_index(drop=True), cfg)
                if sig is None:
                    continue
                first = first or int(df["epoch"].iloc[i])
                side = 1 if sig["sens"] == "ACHAT" else -1
                entry = sig["prix"]
                for var, lv in variantes(df, i, side, entry, float(a14.iloc[i])).items():
                    if lv is None:
                        continue
                    res = issue(df, i, side, entry, *lv)
                    if res is not None:
                        rows.append({"unite": tf, "marche": name, "variante": var, "sens": sig["sens"],
                                     "rsi_confirme": sig["rsi_confirme"], "r": res, "epoch": int(df["epoch"].iloc[i]),
                                     "sl_dist_pct": abs(entry - lv[0]) / entry * 100})
            span = (df["epoch"].iloc[-1] - df["epoch"].iloc[FENETRE]) / 86400
            print(f"  {tf:>3} {name:<20} {span:6.0f} jours analysés")
    res = pd.DataFrame(rows)
    out = Path(__file__).parent / "backtest_resultats.csv"
    res.to_csv(out, index=False)

    def table(d: pd.DataFrame, by) -> pd.DataFrame:
        t = d.groupby(by)["r"].agg(trades="count", gagnants=lambda x: (x > 0).mean() * 100, total_R="sum",
                                   R_moyen="mean")
        return t.round(2)

    pd.set_option("display.width", 200)
    print("\n=== Toutes unités et tous marchés confondus, par variante ===")
    print(table(res, "variante").sort_values("R_moyen", ascending=False).to_string())
    print("\n=== Variante actuelle du bot (SL 10 bougies, TP 2R), par unité ===")
    cur = res[res["variante"] == "SL 10 bougies, TP 2R"]
    print(table(cur, "unite").to_string())
    print("\n=== Variante actuelle, RSI confirmé ou non ===")
    print(table(cur, "rsi_confirme").to_string())
    print("\n=== Variante actuelle, par marché ===")
    print(table(cur, "marche").sort_values("R_moyen", ascending=False).to_string())
    print("\n=== Meilleure variante par unité (R moyen) ===")
    t = table(res, ["unite", "variante"]).reset_index()
    print(t.loc[t.groupby("unite")["R_moyen"].idxmax()].to_string(index=False))
    print(f"\nDétail de chaque trade : {out}")


if __name__ == "__main__":
    main()
