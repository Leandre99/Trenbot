"""Drift Switch Index : le prix a de la mémoire (tendances programmées). Est-ce que ça dépasse le spread ?
Règle testée : on suit le mouvement des L dernières minutes s'il dépasse k fois le bruit normal ;
on sort quand ce mouvement s'inverse. Coûts : spread du broker à chaque trade + portage (7,5 %/an).
Réglage choisi sur la première moitié des données, vérifié sur la seconde.
Usage : python research/dsi_test.py"""
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from numba import njit

sys.path.insert(0, str(Path(__file__).parent))
from lib import HERE                      # noqa: E402
from scan_synth import load_m1            # noqa: E402


@njit(cache=True)
def run(o, c, L, k, sig, spread, hold_max):
    """Retourne (heure d'entrée en indice, gain net en fraction du prix) par trade. Entrée/sortie à l'ouverture suivante."""
    n = len(c)
    ei = np.empty(n, np.int64)
    pn = np.empty(n)
    nt = 0
    pos, entry, e_i = 0, 0.0, 0
    thr = k * sig * np.sqrt(L)
    for i in range(L, n - 1):
        m = np.log(c[i] / c[i - L])
        if pos != 0:
            if m * pos <= 0 or i - e_i >= hold_max:
                px = o[i + 1]
                ei[nt] = e_i
                pn[nt] = (px - entry) * pos / entry - spread / entry
                nt += 1
                pos = 0
        if pos == 0 and abs(m) > thr and thr >= 0:
            pos = 1 if m > 0 else -1
            entry, e_i = o[i + 1], i + 1
    return ei[:nt], pn[:nt]


def main():
    specs = json.loads((HERE / "specs.json").read_text(encoding="utf-8"))
    rows = []
    for sym in ("Drift Switch Index 10", "Drift Switch Index 20", "Drift Switch Index 30", "Volatility 75 Index"):
        d = load_m1(sym)
        o, c = d["open"].to_numpy(float), d["close"].to_numpy(float)
        sp = specs[sym]["spread"] * specs[sym]["point"]
        sig = np.log(d["close"]).diff().std()
        half = len(c) // 2
        for L in (5, 10, 20, 40, 80):
            for k in (0.5, 1.0, 2.0, 3.0):
                ei, pn = run(o, c, L, k, sig, sp, 100000)
                for per, m in (("1re moitié", ei < half), ("2e moitié", ei >= half)):
                    x = pn[m]
                    if len(x) < 20:
                        continue
                    days = (half if per == "1re moitié" else len(c) - half) / 1440
                    rows.append({"indice": sym.replace(" Index", ""), "L": L, "k": k, "periode": per, "trades/jour": len(x) / days,
                                 "net/trade %": x.mean() * 100, "net/trade en spreads": x.mean() / (sp / c.mean()),
                                 "t": x.mean() / x.std(ddof=1) * np.sqrt(len(x)), "gagnants %": (x > 0).mean() * 100,
                                 "net/jour %": x.sum() / days * 100})
    r = pd.DataFrame(rows)
    pd.set_option("display.width", 220)
    a = r[r.periode == "1re moitié"].set_index(["indice", "L", "k"])
    b = r[r.periode == "2e moitié"].set_index(["indice", "L", "k"])
    print("=== Meilleur réglage de la 1re moitié pour chaque indice, puis le MÊME réglage sur la 2e moitié ===")
    for sym in a.index.get_level_values(0).unique():
        best = a.loc[sym]["t"].idxmax()
        for name, t in (("1re", a), ("2e ", b)):
            x = t.loc[(sym, *best)]
            print(f"{sym:22} L={best[0]:3} k={best[1]:3}  {name} moitié : {x['trades/jour']:6.1f} trades/jour  net/trade {x['net/trade %']:+.4f} % "
                  f"({x['net/trade en spreads']:+.2f} spread)  t={x['t']:+6.2f}  gagnants {x['gagnants %']:.0f} %  net/jour {x['net/jour %']:+.3f} %")
    print("\n=== Tous les réglages, t de la 2e moitié (au-dessus de +3 = solide) ===")
    print(b["t"].round(1).unstack("k").to_string())


if __name__ == "__main__":
    main()
