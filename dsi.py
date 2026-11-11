"""Stratégie « Drift Switch » : suivre les tendances programmées du Drift Switch Index 10 de Deriv.

Cet indice alterne des phases de hausse, de baisse et de calme (10 min en moyenne) : son prix a de la mémoire,
contrairement aux Volatility. Règle, à la clôture de chaque bougie d'UNE minute :
  - mouvement = variation du prix sur les L dernières minutes ; bruit = variation normale sur une minute ;
  - sans position : si |mouvement| > k x bruit x racine(L), on entre dans le sens du mouvement ;
  - en position : on sort dès que le mouvement repasse à zéro ou s'inverse ;
  - on n'entre que si le spread est LARGE : Deriv élargit le spread pendant les phases de tendance et le resserre
    pendant les phases calmes ; spread serré = pas de tendance à suivre (dans les tests, ces entrées-là perdent) ;
  - un stop de sécurité reste chez le broker (au cas où le bot ou le PC s'arrête) ; il n'a jamais été touché
    dans les tests, la sortie normale étant l'inversion du mouvement.
Testé sur 69 jours de bougies 1 minute avec le spread enregistré à chaque minute : `python dsi.py`.
L'avantage est mince (il disparaît si le spread réellement payé est 50 % plus large que celui enregistré).
"""
from dataclasses import dataclass

import numpy as np


@dataclass
class DSIParams:
    L: int = 20               # minutes du mouvement suivi
    k: float = 2.0            # seuil d'entrée, en multiples du bruit attendu sur L minutes
    sig_n: int = 3000         # minutes utilisées pour mesurer le bruit (≈ 2 jours)
    stop_mult: float = 2.5    # stop de sécurité = stop_mult x bruit x racine(L)


def noise(c: np.ndarray, n: int) -> float:
    """Écart-type des variations sur une minute (en log), sur les n dernières bougies."""
    r = np.diff(np.log(c[-(n + 1):]))
    return float(r.std(ddof=1)) if len(r) > 30 else float("nan")


def decide(pos: int, c: np.ndarray, p: DSIParams):
    """c = clôtures des bougies 1 minute TERMINÉES. pos = +1 achat ouvert, -1 vente ouverte, 0 rien.
    Retourne (action, mouvement, seuil) ; action = "close", "buy", "sell", "flip_buy", "flip_sell" ou None."""
    if len(c) < p.L + 40:
        return None, 0.0, 0.0
    sig = noise(c, p.sig_n)
    if not sig > 0:
        return None, 0.0, 0.0
    m = float(np.log(c[-1] / c[-1 - p.L]))
    thr = p.k * sig * np.sqrt(p.L)
    want = (1 if m > 0 else -1) if abs(m) > thr else 0
    if pos != 0:
        if m * pos > 0:
            return None, m, thr                       # le mouvement tient : on garde
        if want != 0:
            return ("flip_buy" if want > 0 else "flip_sell"), m, thr
        return "close", m, thr
    if want != 0:
        return ("buy" if want > 0 else "sell"), m, thr
    return None, m, thr


def stop_distance(price: float, c: np.ndarray, p: DSIParams) -> float:
    """Distance du stop de sécurité, en prix."""
    return p.stop_mult * noise(c, p.sig_n) * np.sqrt(p.L) * price


def backtest(o, h, l, c, p: DSIParams, spread, use_stop: bool = True, max_spread_pct: float | None = None,
             min_spread_pct: float | None = None):
    """Rejoue la règle bougie par bougie avec EXACTEMENT `decide` (comme le bot). Entrée/sortie à l'ouverture suivante.
    spread = un nombre, ou un tableau (spread enregistré à chaque bougie). max_spread_pct = filtre du bot à l'entrée.
    Retourne une liste de (indice d'entrée, sens, gain net en fraction du prix, gain en R, sorti au stop ?)."""
    n = len(c)
    sp = spread if isinstance(spread, np.ndarray) else np.full(n, float(spread))
    out = []
    pos, entry, stop, dist, e_i = 0, 0.0, 0.0, 0.0, 0
    lc = np.log(c)
    r = np.diff(lc)
    cs, cs2 = np.concatenate(([0.0], np.cumsum(r))), np.concatenate(([0.0], np.cumsum(r * r)))
    for i in range(p.sig_n + p.L + 1, n - 1):
        if pos != 0 and use_stop:                    # stop de sécurité touché pendant la bougie i
            hit = l[i] <= stop if pos > 0 else h[i] + sp[i] >= stop
            if hit:
                px = min(stop, o[i]) if pos > 0 else max(stop, o[i] + sp[i])
                pnl = (px - entry) * pos
                out.append((e_i, pos, pnl / entry, pnl / dist, True))
                pos = 0
        k0 = i - p.sig_n                             # bruit sur les sig_n dernières variations (identique à noise())
        s, s2 = cs[i] - cs[k0], cs2[i] - cs2[k0]
        sig = np.sqrt(max(s2 - s * s / p.sig_n, 0.0) / (p.sig_n - 1))
        m = lc[i] - lc[i - p.L]
        thr = p.k * sig * np.sqrt(p.L)
        want = (1 if m > 0 else -1) if abs(m) > thr else 0
        if pos != 0 and m * pos <= 0:
            px = o[i + 1] if pos > 0 else o[i + 1] + sp[i + 1]
            pnl = (px - entry) * pos
            out.append((e_i, pos, pnl / entry, pnl / dist, False))
            pos = 0
        if pos == 0 and want != 0 and sig > 0:
            if max_spread_pct is not None and sp[i + 1] / o[i + 1] * 100 > max_spread_pct:
                continue                              # le bot refuse d'entrer quand le spread est large
            if min_spread_pct is not None and sp[i + 1] / o[i + 1] * 100 < min_spread_pct:
                continue                              # spread serré = phase calme de l'indice : pas de tendance à suivre
            pos, e_i = want, i + 1
            entry = o[i + 1] + sp[i + 1] if want > 0 else o[i + 1]
            dist = p.stop_mult * sig * np.sqrt(p.L) * entry
            stop = entry - pos * dist
    return out


if __name__ == "__main__":
    import json
    import sys
    from pathlib import Path

    import pandas as pd

    import config

    here = Path(__file__).parent / "research"
    f = here / "data" / "Drift_Switch_Index_10_M1.npz"
    if not f.exists():
        sys.exit("Données absentes : lance d'abord  python research/scan_synth.py pull")
    rt = np.load(f)["rates"]
    o, h, l, c = (rt[k].astype(float) for k in ("open", "high", "low", "close"))
    t = pd.to_datetime(rt["time"], unit="s")
    pt = json.loads((here / "specs.json").read_text(encoding="utf-8"))["Drift Switch Index 10"]["point"]
    sp = rt["spread"].astype(float) * pt                      # spread enregistré à chaque minute
    half, days = len(c) // 2, (t[-1] - t[0]).total_seconds() / 86400
    p = DSIParams(L=config.DSI_L, k=config.DSI_K, stop_mult=config.DSI_STOP_MULT)
    mn = config.DSI_MIN_SPREAD_PCT
    print(f"Drift Switch Index 10 : {days:.0f} jours de bougies 1 minute | réglage du bot : L={p.L} k={p.k} spread mini {mn} %")
    print(f"{'coûts':34} {'trades/jour':>11} {'net/trade':>10} {'R/trade':>8} {'t':>6} {'gagnants':>8} {'1re moitié':>10} {'2e moitié':>10} {'semaines +':>10}")
    for name, mult, flt in (("spread enregistré, réglage du bot", 1.0, mn), ("spread 25 % plus large", 1.25, mn * 1.25),
                            ("spread 50 % plus large", 1.5, mn * 1.5), ("sans le filtre de phase", 1.0, None)):
        tr = backtest(o, h, l, c, p, sp * mult, min_spread_pct=flt)
        ei = np.array([x[0] for x in tr]); pn = np.array([x[2] for x in tr]); rr = np.array([x[3] for x in tr])
        wk = pd.Series(rr, index=t[ei]).resample("W").sum()
        print(f"{name:34} {len(tr) / days:11.1f} {pn.mean() * 100:+9.4f}% {rr.mean():+8.3f} {rr.mean() / rr.std(ddof=1) * np.sqrt(len(rr)):+6.2f} "
              f"{(pn > 0).mean() * 100:7.0f}% {rr[ei < half].sum():+9.1f}R {rr[ei >= half].sum():+9.1f}R {int((wk > 0).sum()):>7}/{len(wk)}")
