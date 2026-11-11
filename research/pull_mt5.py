"""Télécharge l'historique long depuis le terminal MT5 (lecture seule, aucun ordre).
Sorties : research/data/<symbole>_<TF>.npz et research/specs.json.
Usage : python research/pull_mt5.py
"""
import json
import sys
import time
from pathlib import Path

import MetaTrader5 as mt5
import numpy as np

OUT = Path(__file__).parent / "data"
OUT.mkdir(exist_ok=True)

FOREX = ["EURUSD", "GBPUSD", "USDJPY", "USDCHF", "USDCAD", "AUDUSD", "NZDUSD", "EURGBP", "EURJPY", "EURCHF",
         "EURAUD", "EURCAD", "EURNZD", "GBPJPY", "GBPCHF", "GBPAUD", "GBPCAD", "GBPNZD", "AUDJPY", "AUDCAD",
         "AUDCHF", "AUDNZD", "NZDJPY", "NZDCAD", "NZDCHF", "CADJPY", "CADCHF", "CHFJPY"]
METALS = ["XAUUSD", "XAGUSD", "XPTUSD", "XPDUSD", "XCUUSD"]
INDICES = ["US SP 500", "US Tech 100", "Wall Street 30", "Germany 40", "UK 100", "Japan 225", "France 40",
           "Europe 50", "Australia 200", "Hong Kong 50", "Swiss 20", "US Small Cap 2000"]
ENERGY = ["US Oil", "UK Brent Oil", "NGAS"]
CRYPTO = ["BTCUSD", "ETHUSD", "LTCUSD", "XRPUSD", "SOLUSD", "BNBUSD"]
SYNTH = ["Volatility 10 Index", "Volatility 25 Index", "Volatility 50 Index", "Volatility 75 Index",
         "Volatility 100 Index", "Volatility 10 (1s) Index", "Volatility 25 (1s) Index", "Volatility 50 (1s) Index",
         "Volatility 75 (1s) Index", "Volatility 100 (1s) Index", "Step Index"]
GROUPS = {"forex": FOREX, "metals": METALS, "indices": INDICES, "energy": ENERGY, "crypto": CRYPTO, "synth": SYNTH}

TFS = {"D1": mt5.TIMEFRAME_D1, "H4": mt5.TIMEFRAME_H4, "H1": mt5.TIMEFRAME_H1,
       "M30": mt5.TIMEFRAME_M30, "M15": mt5.TIMEFRAME_M15}
COUNT = 99000


def fname(sym: str, tf: str) -> Path:
    return OUT / f"{sym.replace(' ', '_').replace('(', '').replace(')', '')}_{tf}.npz"


def pull(sym: str, tf_name: str, tf) -> int:
    best = None
    for attempt in range(12):
        r = mt5.copy_rates_from_pos(sym, tf, 0, COUNT)
        if r is not None and len(r) > 0:
            if best is not None and len(r) == len(best):   # stable : le terminal a fini de charger
                break
            best = r
            time.sleep(0.6)
        else:
            time.sleep(1.5)
    if best is None:
        return 0
    tmp = fname(sym, tf_name).with_name("_tmp_" + fname(sym, tf_name).name)     # écriture puis renommage : jamais de fichier à moitié écrit
    np.savez_compressed(tmp, rates=best)
    tmp.replace(fname(sym, tf_name))
    return len(best)


def main():
    if not mt5.initialize():
        sys.exit(f"MT5 indisponible : {mt5.last_error()}")
    specs, restore = {}, []
    only = [a for a in sys.argv[1:] if not a.startswith("--")]
    todo = [(g, s) for g, names in GROUPS.items() for s in names]
    if only:                                   # dans l'ordre demandé
        todo = [(g, s) for want in only for g, s in todo if s == want or g == want]
    p = Path(__file__).parent / "specs.json"

    def save_specs():
        old = json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}
        old.update(specs)
        p.write_text(json.dumps(old, indent=1), encoding="utf-8")

    # versions micro : mêmes prix, mais lots et coûts propres
    for s in mt5.symbols_get():
        if s.name.endswith("micro"):
            d = s._asdict()
            d["group"] = "micro"
            specs[s.name] = {k: v for k, v in d.items() if isinstance(v, (int, float, str, bool))}
    for group, sym in todo:
        info = mt5.symbol_info(sym)
        if info is None:
            print(f"{sym}: absent chez le broker", flush=True)
            continue
        if not info.select:
            mt5.symbol_select(sym, True)
            restore.append(sym)
            (Path(__file__).parent / "restore.txt").write_text(";".join(restore), encoding="utf-8")
            time.sleep(0.3)
            info = mt5.symbol_info(sym)
        d = info._asdict()
        d["group"] = group
        specs[sym] = {k: v for k, v in d.items() if isinstance(v, (int, float, str, bool))}
        got = []
        for tf_name, tf in TFS.items():
            if fname(sym, tf_name).exists() and "--force" not in sys.argv:
                got.append(f"{tf_name}=cache")
                continue
            got.append(f"{tf_name}={pull(sym, tf_name, tf)}")
        print(f"{group:8} {sym:26} " + " ".join(got), flush=True)
        save_specs()
    for sym in restore:           # on remet l'Observation du marché comme avant
        mt5.symbol_select(sym, False)
    mt5.shutdown()
    print("terminé", flush=True)


if __name__ == "__main__":
    main()
