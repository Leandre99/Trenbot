"""Méthode des captures (« smart money ») rendue mécanique, testée sur l'historique MT5.
  A. Prise de liquidité (turtle soup) : le prix dépasse un ancien sommet/creux puis clôture de l'autre côté -> on entre
     contre la cassure, stop derrière la mèche, objectif fixe.
  B. Retour sur la zone d'origine après une cassure de structure : ordre limite sur la bougie qui a lancé le mouvement
     (son niveau « open/close »), stop sous sa mèche, objectif = la liquidité d'en face.
Chaque réglage est aussi joué sur des prix TIRÉS AU HASARD (témoin) : la différence avec le témoin est le seul
avantage réel. Les réglages sont comparés sur la première partie de l'historique ; la seconde sert à vérifier.
Usage : python research/run_s1.py [--holdout]"""
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))
from lib import OUT, atr, fname, load, spread_price, stat           # noqa: E402
from strats import pivots, sweep_kernel, zone_kernel                 # noqa: E402
from test_engine import random_bars                                  # noqa: E402

FOREX = ["EURUSD", "GBPUSD", "USDJPY", "USDCHF", "USDCAD", "AUDUSD", "NZDUSD", "EURGBP", "EURJPY", "EURCHF",
         "EURAUD", "EURCAD", "AUDJPY", "GBPAUD", "GBPJPY", "AUDCAD", "AUDCHF"]
GOLD = ["XAUUSD"]
SYNTH = ["Volatility 10 Index", "Volatility 25 Index", "Volatility 50 Index", "Volatility 75 Index",
         "Volatility 100 Index", "Step Index"]
TF_S = {"M15": 900, "M30": 1800, "H1": 3600, "H4": 14400, "D1": 86400}
SPLIT = 0.55            # première partie = comparaison des réglages, le reste = vérification
MAX_COST_R = 0.15       # règle du bot : pas de trade si le spread dépasse 15 % du risque


def own_levels(h, l, n):
    ih, il = pivots(h, l, n)
    hi, lo = np.flatnonzero(ih), np.flatnonzero(il)
    return hi + n, h[hi], lo + n, l[lo]


def htf_levels(idx: pd.DatetimeIndex, sym: str, htf: str, n: int):
    d = load(sym, htf)
    H, L = d["high"].to_numpy(float), d["low"].to_numpy(float)
    ih, il = pivots(H, L, n)
    t = idx.values
    out = []
    for flags, px in ((ih, H), (il, L)):
        p = np.flatnonzero(flags)
        p = p[p + n < len(d)]
        confirm = d.index.values[p + n] + np.timedelta64(TF_S[htf], "s")      # clôture de la bougie qui confirme
        act = np.searchsorted(t, confirm, side="left") - 1
        keep = act >= 0
        order = np.argsort(act[keep], kind="stable")
        out += [act[keep][order].astype(np.int64), px[p][keep][order]]
    return tuple(out)


def prev_day_levels(idx: pd.DatetimeIndex, h, l):
    day = idx.normalize().values
    change = np.flatnonzero(day[1:] != day[:-1])                 # dernière bougie de chaque journée
    starts = np.concatenate(([0], change + 1))
    ends = np.concatenate((change, [len(idx) - 1]))
    hi = np.array([h[s:e + 1].max() for s, e in zip(starts, ends)])
    lo = np.array([l[s:e + 1].min() for s, e in zip(starts, ends)])
    return ends.astype(np.int64), hi, ends.astype(np.int64), lo


def d1_bias(idx: pd.DatetimeIndex, sym: str, tf: str) -> np.ndarray:
    d = load(sym, "D1")
    b = np.sign(d["close"] - d["close"].ewm(span=50, adjust=False).mean()).to_numpy()
    close_t = d.index.values + np.timedelta64(86400, "s")
    k = np.searchsorted(close_t, idx.values + np.timedelta64(TF_S[tf], "s"), side="right") - 1
    return np.where(k >= 0, b[np.clip(k, 0, None)], 0).astype(np.int64)


# nom -> (famille, paramètres)
CONFIGS = {
    "A1 liquidité, sommets n=10, 2R": ("sweep", dict(src="own", n=10, rr=2.0)),
    "A2 liquidité, sommets n=20, 3R": ("sweep", dict(src="own", n=20, rr=3.0)),
    "A3 liquidité, haut/bas de la veille, 2R": ("sweep", dict(src="day", n=0, rr=2.0)),
    "A4 liquidité, sommets du jour (D1), 3R": ("sweep", dict(src="D1", n=3, rr=3.0)),
    "A5 = A1 + sens de la tendance jour": ("sweep", dict(src="own", n=10, rr=2.0, bias=True)),
    "B0 zone open/close n=5, objectif liquidité": ("zone", dict(n=5, mode=0)),
    "B1 zone bougie entière n=5": ("zone", dict(n=5, mode=2)),
    "B2 zone open/close n=10": ("zone", dict(n=10, mode=0)),
    "B3 = B0 + sens de la tendance jour": ("zone", dict(n=5, mode=0, bias=True)),
    "B4 zone open/close n=5, objectif fixe 5R": ("zone", dict(n=5, mode=0, rr_fixed=5.0)),
}


def run_cfg(kind, p, o, h, l, c, a, idx, sym, tf, spread, min_risk_sp, bias):
    use_bias = bool(p.get("bias")) and bias is not None
    b = bias if use_bias else np.zeros(len(o), np.int64)
    if kind == "sweep":
        if p["src"] == "own":
            lv = own_levels(h, l, p["n"])
        elif p["src"] == "day":
            lv = prev_day_levels(idx, h, l)
        else:
            lv = htf_levels(idx, sym, p["src"], p["n"]) if sym else own_levels(h, l, p["n"] * 24)
        age = int(5 * 86400 / TF_S[tf]) if p["src"] == "day" else int(60 * 86400 / TF_S[tf])
        return sweep_kernel(o, h, l, c, a, lv[0], lv[1], lv[2], lv[3], spread, p["rr"], 0.1, 2000, min_risk_sp, age,
                            b, use_bias, True)
    return zone_kernel(o, h, l, c, a, p["n"], spread, 0.05, min_risk_sp, 2.0, 10.0, p.get("rr_fixed", 0.0), 300, 2000,
                       p["mode"], b, use_bias, True)


def market(sym: str, tf: str, group: str) -> list[dict]:
    df = load(sym, tf)
    o, h, l, c = (df[k].to_numpy(float) for k in ("open", "high", "low", "close"))
    a = atr(h, l, c, 14)
    sp = spread_price(sym)
    bias = d1_bias(df.index, sym, tf)
    cut = df.index[int(len(df) * SPLIT)]
    rows = []
    for name, (kind, p) in CONFIGS.items():
        for label, spread, mrs in (("net", sp, 1 / MAX_COST_R), ("brut", 0.0, 0.0)):
            e_i, x_i, sd, e_px, rk, R = run_cfg(kind, p, o, h, l, c, a, df.index, sym, tf, spread, mrs, bias)
            t = df.index[e_i]
            for per, m in (("réglage", t < cut), ("vérification", t >= cut)):
                rows.append({"cfg": name, "tf": tf, "groupe": group, "sym": sym, "mode": label, "periode": per,
                             "n": int(m.sum()), "sum": float(R[m].sum()), "sumsq": float((R[m] ** 2).sum()),
                             "wins": int((R[m] > 0).sum())})
    return rows


def placebo(tf: str) -> list[dict]:
    rows = []
    for seed in range(3):
        o, h, l, c = random_bars(99_000, 30, 100 + seed, True)
        a = atr(h, l, c, 14)
        idx = pd.date_range("2015-01-01", periods=len(o), freq=f"{TF_S[tf]}s")
        for name, (kind, p) in CONFIGS.items():
            if p.get("bias"):
                continue
            R = run_cfg(kind, p, o, h, l, c, a, idx, None, tf, 0.0, 0.0, None)[5]
            rows.append({"cfg": name, "tf": tf, "groupe": "témoin (hasard)", "sym": f"hasard{seed}", "mode": "brut",
                         "periode": "réglage", "n": len(R), "sum": float(R.sum()), "sumsq": float((R ** 2).sum()),
                         "wins": int((R > 0).sum())})
    return rows


def agg(g: pd.DataFrame) -> pd.Series:
    n, s, ss = g["n"].sum(), g["sum"].sum(), g["sumsq"].sum()
    if n < 2:
        return pd.Series({"n": n, "moy_R": np.nan, "t": np.nan, "total_R": s, "gagnants%": np.nan})
    mean = s / n
    sd = np.sqrt(max(ss / n - mean ** 2, 1e-12) * n / (n - 1))
    return pd.Series({"n": n, "moy_R": mean, "t": mean / sd * np.sqrt(n), "total_R": s, "gagnants%": g["wins"].sum() / n * 100})


def show(res: pd.DataFrame, periode: str):
    r = res[res.periode == periode]
    for tf in ("H1", "M30", "M15"):
        print(f"\n######## {tf} — période de {periode} ########")
        rt = r[r.tf == tf]
        if rt.empty:
            continue
        out = {}
        for (cfg, grp, mode), g in rt.groupby(["cfg", "groupe", "mode"]):
            a_ = agg(g)
            out.setdefault(cfg, {})[f"{grp} {mode} moy"] = round(a_["moy_R"], 3)
            if mode == "net":
                out[cfg][f"{grp} n"] = int(a_["n"])
                out[cfg][f"{grp} t"] = round(a_["t"], 2)
        print(pd.DataFrame(out).T.to_string())


if __name__ == "__main__":
    groups = [a for a in sys.argv[1:] if not a.startswith("--")]
    rows = []
    for tf in ("H1", "M30", "M15"):
        rows += placebo(tf)
        for group, syms in (("forex", FOREX), ("or", GOLD), ("synthétique", SYNTH)):
            if groups and not any(group.startswith(g) for g in groups):
                continue
            for sym in syms:
                if fname(sym, tf).exists() and fname(sym, "D1").exists():
                    try:
                        rows += market(sym, tf, group)
                    except (EOFError, OSError, ValueError) as e:      # fichier en cours d'écriture
                        print("ignoré", sym, tf, repr(e)[:60], flush=True)
        print(tf, "fait", flush=True)
    res = pd.DataFrame(rows)
    res.to_pickle(OUT / f"s1_results_{'_'.join(groups) or 'tout'}.pkl")
    plc = res[res.groupe == "témoin (hasard)"]
    print("\n=== Témoin : prix au hasard, sans spread (ce que le moteur donne quand il n'y a RIEN à gagner) ===")
    print(plc.groupby(["cfg", "tf"]).apply(agg, include_groups=False)[["n", "moy_R", "t"]].round(3).unstack("tf").to_string())
    show(res, "réglage")
    if "--holdout" in sys.argv:
        show(res, "vérification")
