"""Stratégie de la vidéo : analyse descendante (top-down) + rebond sur ligne de tendance.

1. Les lignes de tendance sont tracées sur les grandes échelles (semaine, jour, 4h).
2. On descend en H1 : quand le prix touche une de ces lignes et rebondit (bougie de rejet),
   on entre dans le sens de la ligne (ligne haussière = achat, ligne baissière = vente).
3. Stop-loss juste derrière la ligne.
4. Ensuite le stop suit les nouveaux creux (achat) ou sommets (vente).
   On sort quand le stop est touché, c'est-à-dire quand la tendance se casse.
"""
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from strategy import Params, atr, best_line, find_pivots

GRAN_S = {"H4": 14400, "D1": 86400, "W1": 604800}


@dataclass
class MTFParams:
    htfs: tuple = ("W1", "D1", "H4")   # échelles où l'on trace les lignes (priorité dans l'ordre)
    htf_pivot_n: int = 3
    htf_n_pivots: int = 6
    htf_min_touches: int = 3
    htf_tol_atr: float = 0.25          # tolérance de tracé, en ATR de l'échelle
    touch_atr: float = 0.3             # "toucher" la ligne, en ATR H1
    sl_atr: float = 1.0                # marge du stop derrière la ligne, en ATR H1
    trail_atr: float = 0.25
    pivot_n: int = 3                   # pivots H1 pour le stop suiveur
    atr_n: int = 14
    cost_atr: float = 0.05
    max_bars: int = 2000


def epoch(idx) -> np.ndarray:
    return idx.values.astype("datetime64[s]").astype("int64")


def make_htf(h1: pd.DataFrame, d1: pd.DataFrame) -> dict:
    agg = {"open": "first", "high": "max", "low": "min", "close": "last"}
    out = {
        "H4": h1.resample("4h").agg(agg).dropna(),
        "D1": d1.copy(),
        "W1": d1.resample("W-MON", closed="left", label="left").agg(agg).dropna(),
    }
    return out


def htf_lines(df: pd.DataFrame, gran: int, mp: MTFParams, only_last: bool = False):
    """Pour chaque bougie complétée de l'échelle, les lignes (haussière, baissière) valides.
    Retourne (open_epochs, liste de (up, down)) où up/down = (pente, ordonnée) en indices de bougies."""
    p = Params(pivot_n=mp.htf_pivot_n, n_pivots=mp.htf_n_pivots, min_touches=mp.htf_min_touches,
               tol_atr=mp.htf_tol_atr)
    o, h, l, c = (df[k].to_numpy() for k in ("open", "high", "low", "close"))
    a_all = atr(df, mp.atr_n)
    is_low, is_high = find_pivots(df, p.pivot_n)
    low_idx, high_idx = np.flatnonzero(is_low), np.flatnonzero(is_high)
    res = []
    for k in range(len(df)):
        if only_last and k < len(df) - 1:   # en direct, seule la dernière bougie complétée compte
            res.append((None, None))
            continue
        a = a_all[k]
        up = down = None
        if not np.isnan(a) and a > 0:
            conf = k - p.pivot_n
            idx = low_idx[low_idx <= conf][-p.n_pivots:]
            if len(idx) >= 2:
                ln = best_line(idx, l[idx], c, l, h, k + 1, a, p, "up")
                if ln:
                    up = (ln[0], ln[1], ln[2])
            idx = high_idx[high_idx <= conf][-p.n_pivots:]
            if len(idx) >= 2:
                ln = best_line(idx, h[idx], c, l, h, k + 1, a, p, "down")
                if ln:
                    down = (ln[0], ln[1], ln[2])
        res.append((up, down))
    return epoch(df.index), res


def detect_signal(o, h, l, c, t, i, a, lines, mp: MTFParams):
    """Signal sur la bougie H1 `i` (clôturée). Retourne (sens, valeur_ligne, échelle, touches) ou None.
    Utilisé tel quel par le backtest et par le bot en direct."""
    t_close = t[i] + 3600
    for name in mp.htfs:
        opens, lns = lines[name]
        g = GRAN_S[name]
        k = np.searchsorted(opens + g, t_close, side="right") - 1  # dernière bougie complétée
        if k < 0:
            continue
        pos = k + (t[i] - opens[k]) / g       # position de la bougie H1 dans l'échelle de la ligne
        up, down = lns[k]
        if up is not None:
            lv = up[0] * pos + up[1]
            if l[i] <= lv + mp.touch_atr * a and l[i] >= lv - 2 * a and c[i] > lv and c[i] > o[i]:
                return ("long", lv, name, up[2])
        if down is not None:
            lv = down[0] * pos + down[1]
            if h[i] >= lv - mp.touch_atr * a and h[i] <= lv + 2 * a and c[i] < lv and c[i] < o[i]:
                return ("short", lv, name, down[2])
    return None


def trail_stop(side: str, sl: float, h, l, low_idx, high_idx, entry_i: int, j: int, a: float, mp: MTFParams) -> float:
    """Nouveau stop à la bougie `j` : derrière le dernier pivot confirmé depuis l'entrée. Ne recule jamais."""
    cj = j - mp.pivot_n
    if side == "long":
        pl = low_idx[(low_idx <= cj) & (low_idx > entry_i - mp.pivot_n)]
        return max(sl, l[pl[-1]] - mp.trail_atr * a) if len(pl) else sl
    ph = high_idx[(high_idx <= cj) & (high_idx > entry_i - mp.pivot_n)]
    return min(sl, h[ph[-1]] + mp.trail_atr * a) if len(ph) else sl


def backtest_mtf(h1: pd.DataFrame, d1: pd.DataFrame, mp: MTFParams = MTFParams(), cache: dict | None = None):
    htf = make_htf(h1, d1)
    lines = cache if cache is not None else {}
    for name in mp.htfs:
        if name not in lines:
            lines[name] = htf_lines(htf[name], GRAN_S[name], mp)

    o, h, l, c = (h1[k].to_numpy() for k in ("open", "high", "low", "close"))
    t = epoch(h1.index)
    a_all = atr(h1, mp.atr_n)
    is_low, is_high = find_pivots(h1, mp.pivot_n)
    low_idx, high_idx = np.flatnonzero(is_low), np.flatnonzero(is_high)
    n = len(h1)
    trades = []
    i = max(mp.atr_n, 2 * mp.pivot_n) + 1
    while i < n - 2:
        a = a_all[i]
        if np.isnan(a) or a <= 0:
            i += 1
            continue
        signal = detect_signal(o, h, l, c, t, i, a, lines, mp)
        if signal is None:
            i += 1
            continue

        side, lv, name, touches = signal
        entry_i = i + 1
        entry = o[entry_i]
        sgn = 1 if side == "long" else -1
        sl = lv - sgn * mp.sl_atr * a
        risk = (entry - sl) * sgn
        if risk <= 0:
            i += 1
            continue
        init_sl = sl
        exit_i, exit_px = None, None
        for j in range(entry_i, min(n, entry_i + mp.max_bars)):
            sl = trail_stop(side, sl, h, l, low_idx, high_idx, entry_i, j, a, mp)
            if side == "long" and l[j] <= sl:
                exit_i, exit_px = j, min(sl, o[j])
                break
            if side == "short" and h[j] >= sl:
                exit_i, exit_px = j, max(sl, o[j])
                break
        if exit_i is None:
            exit_i = min(n, entry_i + mp.max_bars) - 1
            exit_px = c[exit_i]
        pnl = (exit_px - entry) * sgn - mp.cost_atr * a
        trades.append({
            "side": side, "line": name, "touches": touches, "line_value": lv,
            "entry_i": entry_i, "exit_i": exit_i,
            "entry_time": h1.index[entry_i], "exit_time": h1.index[exit_i],
            "entry": entry, "exit": exit_px, "init_sl": init_sl,
            "R": pnl / risk, "bars": exit_i - entry_i,
        })
        i = exit_i + 1
    return pd.DataFrame(trades), lines
