"""Indices synthétiques « à structure » de Deriv : y a-t-il une tendance programmée exploitable ?
Deriv décrit les Drift Switch Index comme alternant des phases de hausse, de baisse et de calme (10, 20 ou 30 min
en moyenne). Si c'est vrai, le prix a de la mémoire, contrairement aux Volatility. On le mesure, puis on regarde
si ça dépasse le spread.
  python research/scan_synth.py pull    -> télécharge les bougies 1 minute (lecture seule, aucun ordre)
  python research/scan_synth.py         -> mesures et test
"""
import json
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))
from lib import DATA, HERE, fname                     # noqa: E402

SYMS = ["Drift Switch Index 10", "Drift Switch Index 20", "Drift Switch Index 30", "Trek Up Index", "Trek Down Index",
        "Exponential Growth Index 1", "Exponential Growth Index 2", "Ladder Volatility Up Index",
        "Ladder Volatility Down Index", "Range Break 100 Index", "Range Break 200 Index", "Volatility 75 Index"]


def pull():
    import MetaTrader5 as mt5
    if not mt5.initialize():
        sys.exit(f"MT5 indisponible : {mt5.last_error()}")
    p = HERE / "specs.json"
    specs = json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}
    restore = []
    for sym in SYMS:
        info = mt5.symbol_info(sym)
        if info is None:
            print(sym, ": absent", flush=True)
            continue
        if not info.select:
            mt5.symbol_select(sym, True)
            restore.append(sym)
            time.sleep(0.3)
            info = mt5.symbol_info(sym)
        tick = mt5.symbol_info_tick(sym)
        d = {k: v for k, v in info._asdict().items() if isinstance(v, (int, float, str, bool))}
        d["group"] = "synth"
        d["ask_now"], d["bid_now"] = (tick.ask, tick.bid) if tick else (0.0, 0.0)
        specs[sym] = d
        best = None
        for _ in range(15):
            r = mt5.copy_rates_from_pos(sym, mt5.TIMEFRAME_M1, 0, 99000)
            if r is not None and len(r) > 0:
                if best is not None and len(r) == len(best):
                    break
                best = r
                time.sleep(0.6)
            else:
                time.sleep(1.5)
        n = 0
        if best is not None:
            tmp = fname(sym, "M1").with_name("_tmp_" + fname(sym, "M1").name)
            np.savez_compressed(tmp, rates=best)
            tmp.replace(fname(sym, "M1"))
            n = len(best)
        print(f"{sym:32} M1={n}  spread={info.spread * info.point:.6g}  prix={info.bid:.6g}  swap={info.swap_mode},{info.swap_long},{info.swap_short}", flush=True)
        p.write_text(json.dumps(specs, indent=1), encoding="utf-8")
    for sym in restore:
        mt5.symbol_select(sym, False)
    mt5.shutdown()


def load_m1(sym):
    r = np.load(fname(sym, "M1"))["rates"]
    df = pd.DataFrame({k: r[k] for k in ("open", "high", "low", "close", "spread")})
    df.index = pd.to_datetime(r["time"], unit="s")
    return df


def analyse():
    specs = json.loads((HERE / "specs.json").read_text(encoding="utf-8"))
    print(f"{'indice':30} {'jours':>5} {'vol/min %':>9} {'dérive %/jour':>13} {'t':>6} | rapport de variance (1 = hasard)  5min  15min  60min  240min | autocorr 1min")
    for sym in SYMS:
        if not fname(sym, "M1").exists():
            continue
        d = load_m1(sym)
        r = np.log(d["close"]).diff().dropna()
        days = (d.index[-1] - d.index[0]).total_seconds() / 86400
        s1 = r.std()
        vr = []
        for k in (5, 15, 60, 240):
            rk = np.log(d["close"]).diff(k).dropna()[::k]
            vr.append(rk.var() / (k * r.var()))
        drift_day = r.mean() * 1440 * 100
        t = r.mean() / s1 * np.sqrt(len(r))
        ac1 = r.autocorr(1)
        sw = specs.get(sym, {})
        print(f"{sym:30} {days:5.0f} {s1 * 100:9.4f} {drift_day:13.3f} {t:6.2f} |                                  "
              f"{vr[0]:5.2f} {vr[1]:6.2f} {vr[2]:6.2f} {vr[3]:7.2f} | {ac1:+.3f}   swap an % achat/vente: {sw.get('swap_long')}/{sw.get('swap_short')} (mode {sw.get('swap_mode')})  spread/prix: {sw.get('spread', 0) * sw.get('point', 0) / max(d.close.iloc[-1], 1e-9) * 100:.4f}%")


if __name__ == "__main__":
    if "pull" in sys.argv:
        pull()
    else:
        analyse()
