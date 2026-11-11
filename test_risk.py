"""Tests du calcul de lots. Lancer : python test_risk.py"""
from risk import lot_for_risk


def test_forex_petit_capital_refuse():
    # EURUSD, 100 $, stop à 30 pips : le lot min 0.01 risque 3 $ (3 %) -> accepté à 3 % max, refusé à 2 %
    r = lot_for_risk(100, 1, 2, 1.1000, 1.0970, 0.00001, 1.0, 0.01, 100, 0.01)
    assert r.lots == 0 and "minimum" in r.reason, r
    r = lot_for_risk(100, 1, 3.5, 1.1000, 1.0970, 0.00001, 1.0, 0.01, 100, 0.01)
    assert r.lots == 0.01 and abs(r.risk_money - 3.0) < 1e-6, r


def test_gros_capital_arrondi_au_pas():
    # 10 000 $, risque 1 % = 100 $, stop 30 pips (= 300 $ par lot) -> 0.333 lot -> arrondi vers le bas : 0.33
    r = lot_for_risk(10_000, 1, 3, 1.1000, 1.0970, 0.00001, 1.0, 0.01, 100, 0.01)
    assert r.lots == 0.33 and r.risk_money <= 100.0 + 1e-9, r


def test_ne_depasse_jamais_le_risque_cible_quand_le_lot_min_suffit():
    r = lot_for_risk(100, 1, 3, 100.0, 99.0, 0.01, 0.01, 0.001, 100, 0.001)  # indice synthétique
    assert r.lots > 0 and r.risk_money <= 1.0 + 1e-9, r


def test_specs_invalides():
    r = lot_for_risk(100, 1, 3, 1.0, 1.0, 0.01, 1.0, 0.01, 10, 0.01)
    assert r.lots == 0 and r.reason


def test_petit_capital_stop_resserre():
    from risk import min_lot_stop
    # lot minimum : 0,10 $ par point ; stop prévu 13,2 points ; plancher 5,3 points ; limite 3 %
    d, risk, pct = min_lot_stop(1000, 3, 13.2, 5.3, 0.10)
    assert d == 13.2 and abs(risk - 1.32) < 1e-9                     # gros capital : rien ne change
    d, risk, pct = min_lot_stop(30, 3, 13.2, 5.3, 0.10)
    assert abs(d - 9.0) < 1e-9 and abs(pct - 3.0) < 1e-9             # 30 $ : stop rapproché pile à 3 %
    d, risk, pct = min_lot_stop(10, 3, 13.2, 5.3, 0.10)
    assert d == 5.3 and abs(risk - 0.53) < 1e-9 and pct > 3          # 10 $ : plancher, au-dessus de la limite (signalé)


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("OK", name)
