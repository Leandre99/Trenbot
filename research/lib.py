"""Outils communs de la recherche : chargement de l'historique MT5, coûts réels (spread, swap), statistiques.
Tous les résultats sont en R (1 R = la perte prévue si le stop initial est touché)."""
import json
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).parent
DATA = HERE / "data"
OUT = HERE / "out"
OUT.mkdir(exist_ok=True)

_specs = None


def specs() -> dict:
    global _specs
    if _specs is None:
        _specs = json.loads((HERE / "specs.json").read_text(encoding="utf-8"))
    return _specs


def fname(sym: str, tf: str) -> Path:
    return DATA / f"{sym.replace(' ', '_').replace('(', '').replace(')', '')}_{tf}.npz"


def load(sym: str, tf: str) -> pd.DataFrame:
    """Bougies MT5 (prix bid, heure du serveur = UTC). Colonnes open/high/low/close/spread(points)."""
    r = np.load(fname(sym, tf))["rates"]
    df = pd.DataFrame({k: r[k] for k in ("open", "high", "low", "close", "spread", "tick_volume")})
    df.index = pd.to_datetime(r["time"], unit="s")
    df = df[~df.index.duplicated()].sort_index()
    return df


def daily(sym: str) -> pd.DataFrame:
    """Bougies jour ; la courte bougie du dimanche (ouverture du forex) est fusionnée avec le lundi."""
    d = load(sym, "D1")
    key = d.index.normalize() + pd.to_timedelta((d.index.dayofweek == 6).astype(int), unit="D")
    key = key + pd.to_timedelta((key.dayofweek == 5).astype(int) * 2, unit="D")   # samedi -> lundi
    g = d.groupby(key)
    out = pd.DataFrame({"open": g["open"].first(), "high": g["high"].max(), "low": g["low"].min(),
                        "close": g["close"].last()})
    return out


_costs = None


def spread_price(sym: str) -> float:
    """Spread typique du broker, en prix.
    1) relevé réel en heure normale (sim_specs.json, 27 oct.) quand il existe pour ce symbole ou sa version micro ;
    2) sinon 2,5 x la médiane du spread enregistré dans les bougies H1 de 2026 hors heure de bascule
       (les bougies gardent le spread le plus serré : le spread réellement payé est 2 à 4 fois plus large) ;
    3) sinon le relevé du moment. Le relevé du moment seul n'est pas fiable (pris à l'heure de bascule)."""
    global _costs
    if _costs is None:
        _costs = {}
        sim = HERE.parent / "sim_specs.json"
        if sim.exists():
            for v in json.loads(sim.read_text()).values():
                _costs[v["mt5"]] = v["spread"]
                _costs.setdefault(v["mt5"].replace("micro", ""), v["spread"])
    if sym not in _costs:
        s = specs()[sym]
        data = sym.replace("micro", "")
        est = None
        if fname(data, "H1").exists():
            d = load(data, "H1")
            d = d[(d.index >= "2026-01-01") & ((d.index.hour < 20) | (d.index.hour > 22))]
            if len(d) > 200 and d["spread"].median() > 0:
                est = 2.5 * d["spread"].median() * s["point"]
        _costs[sym] = est if est else s["spread"] * s["point"]
    return _costs[sym]


def swap_per_night(sym: str, price: float) -> tuple[float, float]:
    """Coût de portage par nuit en PRIX pour (achat, vente). Négatif = on paie."""
    s = specs()[sym]
    mode, sl, ss = s.get("swap_mode", 0), s.get("swap_long", 0.0), s.get("swap_short", 0.0)
    if mode == 1:                       # en points
        return sl * s["point"], ss * s["point"]
    if mode in (5, 6):                  # intérêt annuel en % du prix
        return price * sl / 100 / 360, price * ss / 100 / 360
    if mode == 0:
        return 0.0, 0.0
    # modes en devise par lot : on ramène au prix avec la taille du contrat
    cs = s.get("trade_contract_size", 1.0) or 1.0
    return sl / cs, ss / cs


def nights(sym: str, entry: pd.Series, exit_: pd.Series) -> np.ndarray:
    """Nombre de nuits facturées entre l'entrée et la sortie (triple swap le jour prévu par le broker)."""
    s = specs()[sym]
    all_days = s.get("group") in ("synth", "crypto")
    triple = int(s.get("swap_rollover3days", 3))          # 0 = dimanche ... 3 = mercredi (convention MT5)
    e, x = entry.dt.normalize().to_numpy(), exit_.dt.normalize().to_numpy()
    out = np.zeros(len(entry))
    for k in range(len(entry)):
        if x[k] <= e[k]:
            continue
        days = pd.date_range(e[k], x[k], freq="D")[:-1]     # chaque minuit franchi
        if all_days:
            out[k] = len(days)
        else:
            mt5_dow = (days.dayofweek.to_numpy() + 1) % 7   # pandas lundi=0 -> MT5 lundi=1
            wk = mt5_dow[(mt5_dow >= 1) & (mt5_dow <= 5)]
            out[k] = len(wk) + 2 * (wk == triple).sum()
    return out


def add_costs(tr: pd.DataFrame, sym: str, spread_mult: float = 1.0, with_swap: bool = True) -> pd.DataFrame:
    """Ajoute cost_R, swap_R et R (net) à des trades bruts : colonnes side(+1/-1), entry, risk, R_gross, entry_time, exit_time."""
    if tr.empty:
        return tr.assign(cost_R=[], swap_R=[], R=[])
    sp = spread_price(sym) * spread_mult
    tr = tr.copy()
    tr["cost_R"] = sp / tr["risk"]
    if with_swap:
        n = nights(sym, tr["entry_time"], tr["exit_time"])
        sw = np.array([swap_per_night(sym, p)[0 if s > 0 else 1] for p, s in zip(tr["entry"], tr["side"])])
        tr["swap_R"] = n * sw / tr["risk"].to_numpy()
    else:
        tr["swap_R"] = 0.0
    tr["R"] = tr["R_gross"] - tr["cost_R"] + tr["swap_R"]
    return tr


def stat(r: pd.Series) -> dict:
    n = len(r)
    if n == 0:
        return {"n": 0, "moy_R": np.nan, "t": np.nan, "total_R": 0.0, "gagnants%": np.nan, "PF": np.nan, "maxDD_R": 0.0}
    eq = r.cumsum()
    gains, losses = r[r > 0].sum(), -r[r < 0].sum()
    sd = r.std(ddof=1) if n > 1 else np.nan
    return {"n": n, "moy_R": r.mean(), "t": r.mean() / sd * np.sqrt(n) if sd and sd > 0 else np.nan,
            "total_R": r.sum(), "gagnants%": (r > 0).mean() * 100, "PF": gains / losses if losses > 0 else np.inf,
            "maxDD_R": (eq.cummax() - eq).max()}


def table(tr: pd.DataFrame, by, col: str = "R") -> pd.DataFrame:
    rows = {k: stat(g[col]) for k, g in tr.groupby(by)}
    rows["TOTAL"] = stat(tr[col])
    return pd.DataFrame(rows).T


def fmt(t: pd.DataFrame) -> str:
    t = t.copy()
    for c, d in (("moy_R", 3), ("t", 2), ("total_R", 1), ("gagnants%", 1), ("PF", 2), ("maxDD_R", 1)):
        if c in t:
            t[c] = t[c].astype(float).round(d)
    if "n" in t:
        t["n"] = t["n"].astype(int)
    return t.to_string()


def atr(h: np.ndarray, l: np.ndarray, c: np.ndarray, n: int) -> np.ndarray:
    pc = np.roll(c, 1)
    pc[0] = c[0]
    tr = np.maximum(h - l, np.maximum(np.abs(h - pc), np.abs(l - pc)))
    return pd.Series(tr).rolling(n).mean().to_numpy()
