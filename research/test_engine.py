"""Contrôle du moteur de backtest : sur des prix tirés au hasard (aucune tendance, aucun spread), AUCUNE stratégie
ne peut gagner ni perdre en moyenne. Si le moteur trouve un gain ou une perte, c'est lui qui est faux.
Usage : python research/test_engine.py"""
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).parent))
from lib import atr                                                     # noqa: E402
from strats import generic_kernel, pivots, sweep_kernel, zone_kernel   # noqa: E402


def random_bars(n_bars: int, per_bar: int, seed: int, clustered: bool):
    rng = np.random.default_rng(seed)
    inc = rng.normal(0, 1.0, n_bars * per_bar)
    if clustered:      # volatilité qui varie lentement (comme les vrais marchés) : toujours sans tendance
        v = np.exp(np.cumsum(rng.normal(0, 0.02, n_bars)) * 0.2)
        v = np.clip(v / np.median(v), 0.3, 4.0)
        inc *= np.repeat(v, per_bar)
    px = 100000.0 + np.cumsum(inc)
    m = px.reshape(n_bars, per_bar)
    o = np.concatenate(([100000.0], m[:-1, -1]))
    h = np.maximum(m.max(axis=1), o)
    l = np.minimum(m.min(axis=1), o)
    return o, h, l, m[:, -1].copy()


def line(name, r):
    n = len(r)
    se = r.std(ddof=1) / np.sqrt(n)
    flag = "OK" if abs(r.mean() / se) < 3 else "BIAIS ?"
    print(f"  {name:38} n={n:6}  moyenne={r.mean():+.4f} R  (incertitude ±{2 * se:.4f})  t={r.mean() / se:+.2f}  {flag}")
    return abs(r.mean() / se) < 3


def main():
    ok = True
    for clustered in (False, True):
        print(f"\nPrix au hasard, volatilité {'variable' if clustered else 'constante'} — 300 000 bougies, spread nul")
        o, h, l, c = random_bars(300_000, 60, 7 + clustered, clustered)
        a = atr(h, l, c, 14)
        bias = np.zeros(len(o), np.int64)
        for n in (5, 10):
            ih, il = pivots(h, l, n)
            hi, lo = np.flatnonzero(ih), np.flatnonzero(il)
            for rr in (1.0, 3.0):
                r = sweep_kernel(o, h, l, c, a, hi + n, h[hi], lo + n, l[lo], 0.0, rr, 0.1, 500, 0.0, 2000, bias, False, True)[5]
                ok &= line(f"prise de liquidité n={n} rr={rr}", r)
        for mode in (0, 1, 2):
            r = zone_kernel(o, h, l, c, a, 5, 0.0, 0.05, 0.0, 2.0, 10.0, 0.0, 300, 500, mode, bias, False, True)[5]
            ok &= line(f"retour sur zone mode={mode}", r)
            r = zone_kernel(o, h, l, c, a, 5, 0.0, 0.05, 0.0, 0.0, 99.0, 3.0, 300, 500, mode, bias, False, True)[5]
            ok &= line(f"retour sur zone mode={mode} rr fixe 3", r)
        import pandas as pd
        hh = pd.Series(h).rolling(55).max().shift(1).to_numpy()
        ll = pd.Series(l).rolling(55).min().shift(1).to_numpy()
        xh = pd.Series(h).rolling(20).max().shift(1).to_numpy()
        xl = pd.Series(l).rolling(20).min().shift(1).to_numpy()
        r = generic_kernel(o, h, l, c, c > hh, c < ll, c < xl, c > xh, 2 * a, 0.0, 0.0, 5000, 0.0, True)[5]
        ok &= line("cassure de canal 55/20", r)
        r = generic_kernel(o, h, l, c, c > hh, c < ll, c < xl, c > xh, 2 * a, 0.0, 3.0, 5000, 0.0, True)[5]
        ok &= line("cassure de canal + objectif 3R", r)
        r = generic_kernel(o, h, l, c, c > hh, c < ll, np.zeros(len(o), np.bool_), np.zeros(len(o), np.bool_), a, 0.0, 0.0, 5000, 2.0, True)[5]
        ok &= line("cassure + stop suiveur", r)
    print("\nMOTEUR NEUTRE" if ok else "\nATTENTION : le moteur a un biais")
    return ok


if __name__ == "__main__":
    sys.exit(0 if main() else 1)
