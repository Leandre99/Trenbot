"""Stratégie de l'utilisateur : moyennes mobiles simples 8 / 21 / 50 + RSI 14 (niveaux 30 / 50 / 70).
Achat (vente = symétrique), à la clôture d'une bougie :
  - la MM8 passe au-dessus de la MM21 et les deux sont au-dessus de la MM50 (l'alignement vient de se former) ;
  - le prix clôture au-dessus de la MM50 (« le prix casse ») ;
  - RSI, trois lectures testées : A = survente récente (RSI < 30 dans les 20 dernières bougies),
    B = RSI au-dessus de 50, C = sans RSI.
Sorties testées : X1 = croisement inverse MM8/MM21 ; X2 = objectif 2 R. Stop sous le dernier creux (10 bougies).
Coûts réels du broker (spread + portage). Résultats en R.
Usage : python research/run_ma.py"""
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))
from lib import add_costs, atr, fmt, fname, load, spread_price, specs, table   # noqa: E402
from strats import generic_kernel                                               # noqa: E402

GROUPS = {"forex": ["EURUSD", "GBPUSD", "USDJPY", "USDCHF", "USDCAD", "AUDUSD", "NZDUSD", "EURGBP", "EURJPY", "EURCHF",
                    "EURAUD", "EURCAD", "AUDJPY", "GBPAUD", "GBPJPY", "AUDCAD", "AUDCHF"],
          "or": ["XAUUSD"],
          "synthétique": ["Volatility 50 Index", "Volatility 75 Index", "Volatility 100 Index"]}
TFS = ["M15", "M30", "H1", "H4"]


def rsi(c: pd.Series, n=14) -> pd.Series:
    d = c.diff()
    up = d.clip(lower=0).ewm(alpha=1 / n, adjust=False).mean()
    dn = (-d.clip(upper=0)).ewm(alpha=1 / n, adjust=False).mean()
    return 100 - 100 / (1 + up / dn.replace(0, np.nan))


def signals(df: pd.DataFrame):
    C = df["close"]
    m8, m21, m50 = C.rolling(8).mean(), C.rolling(21).mean(), C.rolling(50).mean()
    r = rsi(C)
    up = (m8 > m21) & (m21 > m50) & (C > m50)
    dn = (m8 < m21) & (m21 < m50) & (C < m50)
    new_up, new_dn = up & ~up.shift(1, fill_value=False), dn & ~dn.shift(1, fill_value=False)
    rsi_v = {"A survente/surachat récent": ((r.rolling(20).min() < 30), (r.rolling(20).max() > 70)),
             "B RSI au-dessus/en dessous de 50": ((r > 50), (r < 50)),
             "C sans RSI": (pd.Series(True, index=C.index), pd.Series(True, index=C.index))}
    x_long, x_short = (m8 < m21).to_numpy(), (m8 > m21).to_numpy()
    return {k: ((new_up & a).to_numpy(), (new_dn & b).to_numpy()) for k, (a, b) in rsi_v.items()}, x_long, x_short


def run(sym, tf, group):
    df = load(sym, tf)
    if len(df) < 2000:
        return []
    o, h, l, c = (df[k].to_numpy(float) for k in ("open", "high", "low", "close"))
    a = atr(h, l, c, 14)
    sp = spread_price(sym)
    lo10 = pd.Series(l).rolling(10).min().to_numpy()
    hi10 = pd.Series(h).rolling(10).max().to_numpy()
    sigs, xl, xs = signals(df)
    out = []
    no = np.zeros(len(c), np.bool_)
    for rname, (ls, ss) in sigs.items():
        # distance du stop : sous le dernier creux (achat) / au-dessus du dernier sommet (vente), plus une marge
        d = np.where(ls, c - lo10 + 0.1 * a, np.where(ss, hi10 - c + 0.1 * a, np.nan))
        d = np.where(d > 0.2 * a, d, 0.2 * a)
        for xname, ex_l, ex_s, tr_r in (("X1 sortie au croisement inverse", xl, xs, 0.0), ("X2 objectif 2R", no, no, 2.0)):
            e_i, x_i, sd, e_px, rk, R = generic_kernel(o, h, l, c, ls, ss, ex_l, ex_s, d, sp, tr_r, 100000, 0.0, True)
            tr = pd.DataFrame({"entry_time": df.index[e_i], "exit_time": df.index[x_i], "side": sd, "entry": e_px,
                               "risk": rk, "R_gross": R})
            if tr.empty:
                continue
            tr = add_costs(tr, sym, spread_mult=0.0)       # spread déjà compté par le moteur ; on ajoute le portage
            tr["variante"] = f"{rname} | {xname}"
            tr["tf"], tr["groupe"], tr["sym"] = tf, group, sym
            out.append(tr)
    return out


def main():
    parts = []
    for tf in TFS:
        for group, syms in GROUPS.items():
            for sym in syms:
                if not fname(sym, tf).exists() or sym not in specs():
                    continue
                try:
                    parts += run(sym, tf, group)
                except Exception as e:                       # fichier vide ou abîmé
                    print("ignoré", sym, tf, repr(e)[:60])
        print(tf, "fait", flush=True)
    tr = pd.concat(parts, ignore_index=True)
    # deux moitiés de chaque historique : la stratégie doit tenir sur les deux
    mid = tr.groupby(["tf", "sym"])["entry_time"].transform(lambda s: s.min() + (s.max() - s.min()) / 2)
    tr["moitie"] = np.where(tr.entry_time < mid, "1re", "2e")
    tr.to_pickle(Path(__file__).parent / "out" / "ma_trades.pkl")
    pd.set_option("display.width", 250)
    for tf in TFS:
        t = tr[tr.tf == tf]
        if t.empty:
            continue
        print(f"\n######## {tf} : {t.entry_time.min().date()} -> {t.entry_time.max().date()} ########")
        s = table(t, ["variante", "groupe"])
        print(fmt(s[["n", "moy_R", "t", "gagnants%"]]))


if __name__ == "__main__":
    main()
