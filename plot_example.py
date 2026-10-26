import sys

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

from data import SYMBOLS, get_candles
from mtf import GRAN_S, MTFParams, backtest_mtf, epoch

name = sys.argv[1] if len(sys.argv) > 1 else "Gold (XAU/USD)"
sym = SYMBOLS[name]
h1, d1 = get_candles(sym, "H1", 15000), get_candles(sym, "D1", 3000)
mp = MTFParams()
tr, lines = backtest_mtf(h1, d1, mp)
t = tr.sort_values("R").iloc[-3]          # un des meilleurs trades
print(t[["side", "line", "entry_time", "exit_time", "R"]])

ei, xi = int(t.entry_i), int(t.exit_i)
a, b = max(0, ei - 120), min(len(h1), xi + 40)
seg = h1.iloc[a:b]
opens, lns = lines[t.line]
g = GRAN_S[t.line]
ts = epoch(h1.index)
ys = []
k_entry = np.searchsorted(opens + g, ts[ei] + 3600, side="right") - 1   # ligne connue à l'entrée
ln = lns[k_entry][0] if t.side == "long" else lns[k_entry][1]
for i in range(a, b):
    k = max(0, np.searchsorted(opens, ts[i], side="right") - 1)      # bougie de l'échelle qui contient cette heure
    pos = k + (ts[i] - opens[k]) / g
    ys.append(ln[0] * pos + ln[1])

fig, ax = plt.subplots(figsize=(13, 6))
x = np.arange(a, b)
for xx, (_, r) in zip(x, seg.iterrows()):
    col = "#26a69a" if r.close >= r.open else "#ef5350"
    ax.plot([xx, xx], [r.low, r.high], color=col, lw=1)
    ax.plot([xx, xx], [r.open, r.close], color=col, lw=4)
ax.plot(x, ys, color="#1e88e5", lw=2, label=f"ligne de tendance {t.line}")
ax.axvline(ei, color="gray", ls=":")
ax.scatter([ei], [t.entry], marker="^" if t.side == "long" else "v", s=140, color="black", zorder=5, label="entrée")
ax.scatter([xi], [t.exit], marker="x", s=140, color="purple", zorder=5, label=f"sortie ({t.R:+.1f} R)")
ax.axhline(t.init_sl, color="red", ls="--", lw=1, label="stop initial")
ax.set_title(f"{name} H1 - {'achat' if t.side == 'long' else 'vente'} sur rebond d'une ligne {t.line}")
ax.legend(loc="best")
ax.set_xticks([])
plt.tight_layout()
plt.savefig("exemple_trade.png", dpi=110)
