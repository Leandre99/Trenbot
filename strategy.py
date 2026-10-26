"""Stratégie de rebond sur ligne de tendance (long et short), avec stop suiveur sur la structure.

Règles (v1) :
  1. Pivots : creux/sommets confirmés après `pivot_n` bougies de chaque côté.
  2. Ligne haussière : droite passant par 2 creux, pente > 0, que le prix n'a pas coupée
     (clôture sous la ligne) depuis le premier creux. On garde celle avec le plus de touches.
     Ligne baissière : symétrique avec les sommets.
  3. Entrée : la bougie touche la ligne et clôture du bon côté avec une bougie de rejet
     (haussière pour un long, baissière pour un short). Exécution à l'ouverture suivante.
  4. SL initial : au-delà de la ligne, de `sl_atr` x ATR.
  5. Suivi : à chaque nouveau pivot dans le sens de la tendance, le SL est ramené derrière lui.
  6. Sortie : le SL est touché (ce qui arrive quand la structure/ligne est cassée).
Les résultats sont exprimés en multiples de R (R = distance initiale au SL).
"""
from dataclasses import dataclass

import numpy as np
import pandas as pd


@dataclass
class Params:
    pivot_n: int = 5          # bougies de chaque côté pour valider un pivot
    n_pivots: int = 6         # nb de pivots récents considérés pour tracer les lignes
    min_touches: int = 3      # nb min de points sur la ligne (2 pivots + 1 touche = ligne confirmée)
    tol_atr: float = 0.25     # tolérance de "touche" en ATR
    sl_atr: float = 0.5       # marge du SL au-delà de la ligne, en ATR
    trail_atr: float = 0.25   # marge du stop suiveur derrière le dernier pivot, en ATR
    min_slope_atr: float = 0.0  # pente minimale par bougie, en ATR (0 = juste > 0)
    atr_n: int = 14
    cost_atr: float = 0.0     # coût (spread) par trade, en ATR, soustrait du résultat
    allow_long: bool = True
    allow_short: bool = True
    max_bars: int = 2000      # garde-fou : sortie forcée


def atr(df: pd.DataFrame, n: int) -> np.ndarray:
    pc = df["close"].shift(1)
    tr = pd.concat([df["high"] - df["low"], (df["high"] - pc).abs(), (df["low"] - pc).abs()], axis=1).max(axis=1)
    return tr.rolling(n).mean().to_numpy()


def find_pivots(df: pd.DataFrame, n: int):
    """Retourne deux tableaux booléens (creux, sommets) indexés au pivot lui-même."""
    low, high = df["low"].to_numpy(), df["high"].to_numpy()
    size = len(df)
    is_low = np.zeros(size, bool)
    is_high = np.zeros(size, bool)
    for i in range(n, size - n):
        w_l, w_h = low[i - n:i + n + 1], high[i - n:i + n + 1]
        if low[i] == w_l.min() and (w_l == low[i]).sum() == 1:
            is_low[i] = True
        if high[i] == w_h.max() and (w_h == high[i]).sum() == 1:
            is_high[i] = True
    return is_low, is_high


def best_line(piv_idx, piv_px, close, low, high, i, a, p: Params, side: str):
    """Meilleure ligne de tendance valide à la bougie i. side='up' (creux) ou 'down' (sommets).
    Retourne (pente, ordonnée, touches) ou None."""
    best = None
    k = len(piv_idx)
    tol = p.tol_atr * a
    for x in range(k - 1):
        for y in range(x + 1, k):
            i1, i2 = piv_idx[x], piv_idx[y]
            p1, p2 = piv_px[x], piv_px[y]
            slope = (p2 - p1) / (i2 - i1)
            if side == "up" and slope <= p.min_slope_atr * a:
                continue
            if side == "down" and slope >= -p.min_slope_atr * a:
                continue
            seg = np.arange(i1, i)  # jusqu'à la bougie précédente
            line = p1 + slope * (seg - i1)
            # la ligne ne doit pas avoir été coupée en clôture
            if side == "up" and (close[i1:i] < line - tol).any():
                continue
            if side == "down" and (close[i1:i] > line + tol).any():
                continue
            # touches : pivots proches de la ligne
            touches = 0
            for z in range(k):
                if piv_idx[z] < i1:
                    continue
                lv = p1 + slope * (piv_idx[z] - i1)
                if abs(piv_px[z] - lv) <= tol:
                    touches += 1
            if touches < max(2, p.min_touches - 1):
                continue
            if best is None or touches > best[2] or (touches == best[2] and i2 > best[3]):
                best = (slope, p1 - slope * i1, touches, i2)
    return best


def backtest(df: pd.DataFrame, p: Params = Params()) -> pd.DataFrame:
    o, h, l, c = (df[k].to_numpy() for k in ("open", "high", "low", "close"))
    a_all = atr(df, p.atr_n)
    is_low, is_high = find_pivots(df, p.pivot_n)
    low_idx = np.flatnonzero(is_low)
    high_idx = np.flatnonzero(is_high)
    n = len(df)
    trades = []
    i = max(p.atr_n, 2 * p.pivot_n) + 1
    while i < n - 2:
        a = a_all[i]
        if np.isnan(a) or a <= 0:
            i += 1
            continue
        confirmed = i - p.pivot_n  # pivot confirmé seulement pivot_n bougies plus tard
        signal = None
        if p.allow_long:
            idx = low_idx[low_idx <= confirmed][-p.n_pivots:]
            if len(idx) >= 2:
                ln = best_line(idx, l[idx], c, l, h, i, a, p, "up")
                if ln:
                    lv = ln[0] * i + ln[1]
                    if l[i] <= lv + p.tol_atr * a and c[i] > lv and c[i] > o[i]:
                        signal = ("long", lv, ln)
        if signal is None and p.allow_short:
            idx = high_idx[high_idx <= confirmed][-p.n_pivots:]
            if len(idx) >= 2:
                ln = best_line(idx, h[idx], c, l, h, i, a, p, "down")
                if ln:
                    lv = ln[0] * i + ln[1]
                    if h[i] >= lv - p.tol_atr * a and c[i] < lv and c[i] < o[i]:
                        signal = ("short", lv, ln)
        if signal is None:
            i += 1
            continue

        side, lv, ln = signal
        entry_i = i + 1
        entry = o[entry_i]
        sgn = 1 if side == "long" else -1
        sl = lv - sgn * p.sl_atr * a
        risk = (entry - sl) * sgn
        if risk <= 0:
            i += 1
            continue
        init_sl = sl
        exit_i, exit_px, reason = None, None, "max_bars"
        for j in range(entry_i, min(n, entry_i + p.max_bars)):
            # stop suiveur : dernier pivot confirmé dans le sens de la tendance
            cj = j - p.pivot_n
            if side == "long":
                pl = low_idx[(low_idx <= cj) & (low_idx > entry_i - p.pivot_n)]
                if len(pl):
                    sl = max(sl, l[pl[-1]] - p.trail_atr * a)
                if l[j] <= sl:
                    exit_i, exit_px, reason = j, min(sl, o[j]), "stop"
                    break
            else:
                ph = high_idx[(high_idx <= cj) & (high_idx > entry_i - p.pivot_n)]
                if len(ph):
                    sl = min(sl, h[ph[-1]] + p.trail_atr * a)
                if h[j] >= sl:
                    exit_i, exit_px, reason = j, max(sl, o[j]), "stop"
                    break
        if exit_i is None:
            exit_i = min(n, entry_i + p.max_bars) - 1
            exit_px = c[exit_i]
        pnl = (exit_px - entry) * sgn - p.cost_atr * a
        trades.append({
            "side": side, "entry_time": df.index[entry_i], "exit_time": df.index[exit_i],
            "entry": entry, "exit": exit_px, "init_sl": init_sl, "R": pnl / risk,
            "bars": exit_i - entry_i, "touches": ln[2], "reason": reason,
        })
        i = exit_i + 1  # une seule position à la fois
    return pd.DataFrame(trades)


def stats(tr: pd.DataFrame) -> dict:
    if tr.empty:
        return {"trades": 0}
    r = tr["R"]
    eq = r.cumsum()
    dd = (eq.cummax() - eq).max()
    gains, losses = r[r > 0].sum(), -r[r < 0].sum()
    return {
        "trades": len(tr),
        "win%": round((r > 0).mean() * 100, 1),
        "avg_R": round(r.mean(), 3),
        "total_R": round(r.sum(), 1),
        "PF": round(gains / losses, 2) if losses > 0 else float("inf"),
        "maxDD_R": round(dd, 1),
        "avg_bars": round(tr["bars"].mean(), 1),
    }
