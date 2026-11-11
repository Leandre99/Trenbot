"""Tests du bot (sans MT5 ni argent). Lancer : python test_bot.py
Les données de test sont fabriquées : on connaît à l'avance la bonne réponse."""
import numpy as np

from mtf import GRAN_S, MTFParams, detect_signal, htf_lines, trail_stop
from risk import daily_halt, lot_for_risk, spread_cost_r
from strategy import Params, best_line


# ---------------------------------------------------------------- risque
def test_spread_cost_r():
    assert abs(spread_cost_r(0.00078, 0.98409, 0.98510) - 0.7723) < 1e-3      # le cas AUD/CAD de l'essai à blanc
    assert spread_cost_r(0.0001, 1.10, 1.09) < 0.15                            # forex normal : accepté
    assert spread_cost_r(0.1, 100.0, 100.0) == float("inf")                    # stop nul : refusé


def test_daily_halt():
    assert not daily_halt(100, 100, 3)
    assert not daily_halt(97.5, 100, 3)
    assert daily_halt(96.9, 100, 3)
    assert daily_halt(0, 100, 3) and daily_halt(-5, 100, 3)


def test_arret_du_jour_ne_regarde_que_le_bot():
    from risk import bot_day_halt
    assert not bot_day_halt(0.0, 27.66, 3)          # rien perdu : on trade
    assert not bot_day_halt(-0.5, 27.66, 3)         # -0,50 $ < limite 0,83 $
    assert bot_day_halt(-0.83, 27.66, 3)            # limite atteinte
    assert bot_day_halt(-5.0, 27.66, 3)
    assert not bot_day_halt(+3.0, 27.66, 3)         # le bot gagne : jamais bloqué
    assert bot_day_halt(-0.1, 0, 3)                 # capital nul : bloqué
    # le cas du bug : ancien départ à 100 $, capital réel 27,66 $ -> l'ancien test aurait bloqué à tort
    assert daily_halt(27.66, 100.0, 3) and not bot_day_halt(0.0, 27.66, 3)


def test_lot_jamais_au_dessus_du_risque_cible():
    rng = np.random.default_rng(1)
    for _ in range(500):
        equity = float(rng.uniform(50, 5000))
        entry = float(rng.uniform(1, 5000))
        dist = entry * float(rng.uniform(0.0005, 0.02))
        r = lot_for_risk(equity, 1.0, 3.0, entry, entry - dist, 0.01, float(rng.uniform(0.01, 2)),
                         0.01, 100, 0.01)
        if r.lots > 0:
            # soit on respecte le risque visé (1 %), soit c'est le lot minimum et on reste sous le plafond (3 %)
            assert r.risk_pct <= 1.0 + 1e-6 or (r.lots == 0.01 and r.risk_pct <= 3.0 + 1e-6), r


# ---------------------------------------------------------------- lignes de tendance
def _line_arrays(n=60, slope=0.5, inter=100.0):
    x = np.arange(n)
    y = inter + slope * x
    return x, y


def test_best_line_trouve_la_ligne_haussiere():
    x, y = _line_arrays()
    close, low, high = y + 3, y + 2, y + 4
    piv = np.array([10, 30, 50])
    low[piv] = y[piv]
    ln = best_line(piv, low[piv], close, low, high, 59, 2.0, Params(), "up")
    assert ln is not None
    slope, inter, touches, _ = ln
    assert abs(slope - 0.5) < 1e-9 and abs(inter - 100.0) < 1e-9 and touches == 3


def test_best_line_rejette_une_ligne_coupee():
    x, y = _line_arrays()
    close, low, high = y + 3, y + 2, y + 4
    piv = np.array([10, 30, 50])
    low[piv] = y[piv]
    close[40] = y[40] - 5          # le prix clôture sous la ligne : elle n'est plus valable
    assert best_line(piv, low[piv], close, low, high, 59, 2.0, Params(), "up") is None


def test_best_line_baissiere():
    x = np.arange(60)
    y = 200 - 0.5 * x
    close, high, low = y - 3, y - 2, y - 4
    piv = np.array([10, 30, 50])
    high[piv] = y[piv]
    ln = best_line(piv, high[piv], close, low, high, 59, 2.0, Params(), "down")
    assert ln is not None and abs(ln[0] + 0.5) < 1e-9


def test_only_last_donne_la_meme_ligne_que_le_calcul_complet():
    """En direct on ne calcule que la dernière bougie : le résultat doit être identique au calcul complet."""
    from data import get_candles
    h1, d1 = get_candles("R_75", "H1", 15000), get_candles("R_75", "D1", 3000)
    agg = {"open": "first", "high": "max", "low": "min", "close": "last"}
    mp = MTFParams()
    for df in (d1.tail(500), h1.resample("4h").agg(agg).dropna().tail(600)):
        full = htf_lines(df, 0, mp)
        last = htf_lines(df, 0, mp, only_last=True)
        assert full[1][-1] == last[1][-1]
        assert np.array_equal(full[0], last[0])


# ---------------------------------------------------------------- signaux
def _fake_lines(slope=1.0, inter=100.0, side="up", touches=3):
    opens = np.arange(10) * 86400
    ln = (slope, inter, touches)
    lns = [(None, None)] * 9 + [(ln, None) if side == "up" else (None, ln)]
    return {"D1": (opens, lns)}, opens


def _line_value(t, opens, slope, inter):
    return slope * (9 + (t - opens[9]) / 86400) + inter


def test_signal_long_au_rebond():
    lines, opens = _fake_lines()
    t = np.array([opens[9] + 86400 + 5 * 3600])
    lv = _line_value(t[0], opens, 1.0, 100.0)
    mp = MTFParams(htfs=("D1",))
    # bougie haussière dont la mèche touche la ligne et qui clôture au-dessus
    o, h, l, c = (np.array([x]) for x in (lv - 0.02, lv + 0.2, lv - 0.05, lv + 0.1))
    sig = detect_signal(o, h, l, c, t, 0, 0.5, lines, mp)
    assert sig is not None and sig[0] == "long" and abs(sig[1] - lv) < 1e-9 and sig[2] == "D1"
    # même bougie mais baissière : pas de signal
    o2, c2 = np.array([lv + 0.1]), np.array([lv - 0.02 + 0.0])
    assert detect_signal(o2, h, l, np.array([lv + 0.05]), t, 0, 0.5, lines, mp) is None
    # clôture sous la ligne : pas de signal
    assert detect_signal(o, h, l, np.array([lv - 0.1]), t, 0, 0.5, lines, mp) is None
    # bougie loin au-dessus de la ligne (pas de touche) : pas de signal
    assert detect_signal(o, np.array([lv + 5]), np.array([lv + 3]), np.array([lv + 4]), t, 0, 0.5, lines, mp) is None


def test_signal_short_au_rebond():
    lines, opens = _fake_lines(slope=-1.0, inter=300.0, side="down")
    t = np.array([opens[9] + 86400 + 5 * 3600])
    lv = _line_value(t[0], opens, -1.0, 300.0)
    mp = MTFParams(htfs=("D1",))
    o, h, l, c = (np.array([x]) for x in (lv + 0.02, lv + 0.05, lv - 0.2, lv - 0.1))
    sig = detect_signal(o, h, l, c, t, 0, 0.5, lines, mp)
    assert sig is not None and sig[0] == "short"


def test_signal_deux_temps_donne_un_stop_sous_le_creux():
    lines, opens = _fake_lines()
    n = 30
    t = opens[9] + 86400 + 3600 * np.arange(n)
    lv = np.array([_line_value(x, opens, 1.0, 100.0) for x in t])
    o, c = lv + 1, lv + 1
    h, l = lv + 1.5, lv + 0.5
    for j in (24, 25, 26):                 # le prix casse la ligne (teste la zone du stop)
        l[j], c[j] = lv[j] - 1.0, lv[j] - 0.3
    c[28], l[28] = lv[28] - 0.2, lv[28] - 0.4           # dernière clôture sous la ligne
    o[29], c[29], l[29], h[29] = lv[29] - 0.1, lv[29] + 0.3, lv[29] - 0.2, lv[29] + 0.4   # reprise haussière
    mp = MTFParams(htfs=("D1",), entry_mode="reclaim", reclaim_depth=0.5)
    sig = detect_signal(o, h, l, c, t, 29, 1.0, lines, mp)
    assert sig is not None and sig[0] == "long" and len(sig) == 5
    assert sig[4] < l[24:29].min()          # stop sous le plus bas du test


# ---------------------------------------------------------------- stop suiveur
def test_stop_suiveur_ne_recule_jamais():
    rng = np.random.default_rng(7)
    n = 300
    price = 100 + np.cumsum(rng.normal(0, 1, n))
    h, l = price + rng.uniform(0.1, 1, n), price - rng.uniform(0.1, 1, n)
    from strategy import find_pivots
    mp = MTFParams()
    is_low, is_high = find_pivots(__import__("pandas").DataFrame({"low": l, "high": h}), mp.pivot_n)
    low_idx, high_idx = np.flatnonzero(is_low), np.flatnonzero(is_high)
    sl_long, sl_short = price[50] - 5, price[50] + 5
    prev_l, prev_s = sl_long, sl_short
    for j in range(50, n):
        sl_long = trail_stop("long", sl_long, h, l, low_idx, high_idx, 50, j, 1.0, mp)
        sl_short = trail_stop("short", sl_short, h, l, low_idx, high_idx, 50, j, 1.0, mp)
        assert sl_long >= prev_l and sl_short <= prev_s
        prev_l, prev_s = sl_long, sl_short


# ---------------------------------------------------------------- stratégie Drift Switch
def _dsi_series(drift_last=0.0, n=400, seed=3):
    """Prix au hasard (bruit 0,04 % par minute) puis une dérive par minute sur les 20 dernières bougies."""
    rng = np.random.default_rng(seed)
    r = rng.normal(0, 0.0004, n)
    r[-20:] = drift_last
    return 2650 * np.exp(np.cumsum(r))


def test_dsi_entre_dans_le_sens_du_mouvement():
    from dsi import DSIParams, decide
    p = DSIParams(L=20, k=2.0, sig_n=300)
    assert decide(0, _dsi_series(+0.0005), p)[0] == "buy"
    assert decide(0, _dsi_series(-0.0005), p)[0] == "sell"
    assert decide(0, _dsi_series(+0.00002), p)[0] is None        # mouvement trop petit : on ne fait rien


def test_dsi_sort_quand_le_mouvement_s_inverse():
    from dsi import DSIParams, decide
    p = DSIParams(L=20, k=2.0, sig_n=300)
    assert decide(+1, _dsi_series(+0.0005), p)[0] is None         # l'achat suit la hausse : on garde
    assert decide(+1, _dsi_series(-0.00002), p)[0] == "close"     # la hausse s'est éteinte : on sort
    assert decide(+1, _dsi_series(-0.0005), p)[0] == "flip_sell"  # forte baisse : on sort et on vend
    assert decide(-1, _dsi_series(+0.0005), p)[0] == "flip_buy"
    assert decide(0, np.full(30, 2650.0), p)[0] is None           # pas assez d'historique


def test_dsi_backtest_suit_la_meme_regle_et_ne_gagne_rien_au_hasard():
    from dsi import DSIParams, backtest
    rng = np.random.default_rng(11)
    c = 2650 * np.exp(np.cumsum(rng.normal(0, 0.0004, 60000)))
    o = np.concatenate(([c[0]], c[:-1]))
    tr = backtest(o, np.maximum(o, c), np.minimum(o, c), c, DSIParams(L=20, k=2.0, sig_n=500), 0.0)
    r = np.array([x[3] for x in tr])
    assert len(r) > 200 and abs(r.mean() / (r.std(ddof=1) / np.sqrt(len(r)))) < 3     # hasard sans spread : ni gain ni perte


# ---------------------------------------------------------------- export pour l'indicateur MT5
def test_export_rows_format():
    import live_mt5
    opens = np.arange(100) * 86400 + 1_700_000_000
    lns = [(None, None)] * 99 + [((0.5, 10.0, 3), None)]
    rows = live_mt5.export_rows("EURUSD", {"D1": (opens, lns)})
    assert rows, "aucune ligne exportée"
    parts = [r.split(",") for r in rows]
    assert all(len(p) == 7 and p[0] == "EURUSD" and p[1] == "D1" and p[2] == "up" for p in parts)
    times = [int(p[5]) for p in parts]
    assert times == sorted(times) and int(parts[-1][5]) > int(opens[-1])   # la ligne se prolonge dans le futur
    seqs = [int(p[4]) for p in parts]
    assert seqs == list(range(len(seqs)))


if __name__ == "__main__":
    failed = 0
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            try:
                fn()
                print("OK   ", name)
            except Exception as e:  # noqa: BLE001
                failed += 1
                print("ÉCHEC", name, "->", repr(e)[:200])
    print(f"\n{'TOUS LES TESTS PASSENT' if not failed else str(failed) + ' TEST(S) EN ÉCHEC'}")
    raise SystemExit(1 if failed else 0)
