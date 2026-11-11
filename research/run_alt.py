"""Stratégies différentes, testées avec les mêmes règles de preuve (spread + portage réels du broker).
  T1 / T2  suivi de tendance en bougies jour : cassure du plus haut de 55 (ou 20) jours, sortie sur le plus bas de 20 (ou 10)
  M1       achat des replis sur indices boursiers en tendance haussière (RSI 2 jours < 10 au-dessus de la moyenne 200 jours)
  F1       retour à la moyenne en 4 heures sur le forex (RSI 2 < 5 / > 95, sortie à la moyenne 5)
Réglages fixés à l'avance (valeurs classiques des livres, aucune optimisation).
Période de comparaison : avant 2018. Période de vérification : 2018 et après.
Usage : python research/run_alt.py [--holdout]"""
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))
from lib import OUT, add_costs, atr, daily, fmt, fname, load, spread_price, specs, table   # noqa: E402
from strats import generic_kernel                                                           # noqa: E402

FOREX = ["EURUSD", "GBPUSD", "USDJPY", "USDCHF", "USDCAD", "AUDUSD", "NZDUSD", "EURGBP", "EURJPY", "EURCHF",
         "EURAUD", "EURCAD", "AUDJPY", "GBPAUD", "GBPJPY", "AUDCAD", "AUDCHF"]
GROUPS = {"forex": FOREX, "or/argent": ["XAUUSD", "XAGUSD"],
          "indices boursiers": ["US SP 500", "US Tech 100", "Wall Street 30", "Germany 40", "UK 100", "Japan 225"],
          "pétrole": ["US Oil"], "crypto": ["BTCUSD", "ETHUSD"],
          "synthétique": ["Volatility 10 Index", "Volatility 25 Index", "Volatility 50 Index", "Volatility 75 Index",
                          "Volatility 100 Index", "Step Index"]}
CUT = pd.Timestamp("2018-01-01")
F = np.zeros(0, np.bool_)


def rsi(close: pd.Series, n: int) -> pd.Series:
    d = close.diff()
    up, dn = d.clip(lower=0), -d.clip(upper=0)
    ru, rd = up.ewm(alpha=1 / n, adjust=False).mean(), dn.ewm(alpha=1 / n, adjust=False).mean()
    return 100 - 100 / (1 + ru / rd.replace(0, np.nan))


def to_trades(df, out, sym, strat, group):
    e_i, x_i, sd, e_px, rk, R = out
    tr = pd.DataFrame({"strat": strat, "groupe": group, "sym": sym, "entry_time": df.index[e_i], "exit_time": df.index[x_i],
                       "side": sd, "entry": e_px, "risk": rk, "R_gross": R, "bars": x_i - e_i})
    if tr.empty:
        return tr
    tr = add_costs(tr, sym, spread_mult=0.0)          # le spread est déjà compté par le noyau ; on ajoute le portage
    tr["spread_R"] = spread_price(sym) / tr["risk"]
    return tr


def arrays(df):
    return tuple(df[k].to_numpy(float) for k in ("open", "high", "low", "close"))


def donchian(df, sym, n_in, n_out, group, name, long_only=False):
    o, h, l, c = arrays(df)
    H, L, C = df["high"], df["low"], df["close"]
    hh, ll = H.rolling(n_in).max().shift(1), L.rolling(n_in).min().shift(1)
    xl, xh = L.rolling(n_out).min().shift(1), H.rolling(n_out).max().shift(1)
    a = atr(h, l, c, 20)
    ls, ss = (C > hh).to_numpy(), (C < ll).to_numpy()
    if long_only:
        ss = np.zeros(len(c), np.bool_)
    out = generic_kernel(o, h, l, c, ls, ss, (C < xl).to_numpy(), (C > xh).to_numpy(), 2.0 * a, spread_price(sym),
                         0.0, 100000, 0.0, True)
    return to_trades(df, out, sym, name, group)


def dip_buy(df, sym, group, name="M1 achat des replis (indices)"):
    o, h, l, c = arrays(df)
    C = df["close"]
    ls = ((C > C.rolling(200).mean()) & (rsi(C, 2) < 10)).to_numpy()
    xl = (C > C.rolling(5).mean()).to_numpy()
    no = np.zeros(len(c), np.bool_)
    out = generic_kernel(o, h, l, c, ls, no, xl, no, 3.0 * atr(h, l, c, 14), spread_price(sym), 0.0, 10, 0.0, True)
    return to_trades(df, out, sym, name, group)


def fx_revert(df, sym, group, name="F1 retour à la moyenne 4h"):
    o, h, l, c = arrays(df)
    C = df["close"]
    r = rsi(C, 2)
    m5 = C.rolling(5).mean()
    out = generic_kernel(o, h, l, c, (r < 5).to_numpy(), (r > 95).to_numpy(), (C > m5).to_numpy(), (C < m5).to_numpy(),
                         3.0 * atr(h, l, c, 14), spread_price(sym), 0.0, 30, 0.0, True)
    return to_trades(df, out, sym, name, group)


def main():
    all_tr = []
    for group, syms in GROUPS.items():
        for sym in syms:
            if not fname(sym, "D1").exists() or sym not in specs():
                continue
            d = daily(sym)
            if len(d) < 400:
                continue
            all_tr.append(donchian(d, sym, 55, 20, group, "T1 tendance 55/20 jours"))
            all_tr.append(donchian(d, sym, 20, 10, group, "T2 tendance 20/10 jours"))
            all_tr.append(donchian(d, sym, 55, 20, group, "T1L tendance 55/20, achats seuls", long_only=True))
            if group in ("indices boursiers",):
                all_tr.append(dip_buy(d, sym, group))
            if group in ("forex", "or/argent") and fname(sym, "H4").exists():
                all_tr.append(fx_revert(load(sym, "H4"), sym, group))
            print(f"{group:18} {sym:22} D1 {d.index[0].date()} -> {d.index[-1].date()}", flush=True)
    tr = pd.concat([t for t in all_tr if len(t)], ignore_index=True)
    tr["periode"] = np.where(tr.entry_time < CUT, "réglage (<2018)", "vérification (2018+)")
    tr.to_pickle(OUT / "alt_trades.pkl")
    design = tr[tr.entry_time < CUT]
    print("\n=== PÉRIODE DE COMPARAISON (avant 2018) — R net (spread + portage) ===")
    print(fmt(table(design, ["strat", "groupe"])))
    if "--holdout" in sys.argv:
        hold = tr[tr.entry_time >= CUT]
        print("\n=== PÉRIODE DE VÉRIFICATION (2018 et après) ===")
        print(fmt(table(hold, ["strat", "groupe"])))
        print("\n=== Coûts moyens par trade (R) et durée (jours ou bougies) ===")
        print(tr.groupby(["strat", "groupe"])[["spread_R", "swap_R", "bars"]].mean().round(3).to_string())


if __name__ == "__main__":
    main()
