"""Tests du bot de signaux (données fabriquées, rien n'est envoyé). python test_signaux.py"""
import numpy as np
import pandas as pd

import signaux as s

P = dict(s.DEFAULT)


def frame(close: np.ndarray) -> pd.DataFrame:
    o = np.concatenate(([close[0]], close[:-1]))
    return pd.DataFrame({"epoch": np.arange(len(close)) * 3600, "open": o, "high": np.maximum(o, close) + 0.05,
                         "low": np.minimum(o, close) - 0.05, "close": close})


def path_down_then_up(n_up: int) -> np.ndarray:
    """Baisse (le RSI passe en survente) puis remontée progressive."""
    down = np.linspace(110, 100, 60)
    up = 100 + np.cumsum(np.full(n_up, 0.6))
    return np.concatenate((np.full(40, 110.0), down, up))


def first_signal(close: np.ndarray):
    """Rejoue bougie par bougie comme en direct : premier signal et sa position."""
    for i in range(80, len(close) + 1):
        sig = s.detect(frame(close[:i]), P)
        if sig:
            return i, sig
    return None, None


def test_achat_apres_survente_et_croisements():
    i, sig = first_signal(path_down_then_up(60))
    assert sig is not None and sig["sens"] == "ACHAT"
    assert sig["stop"] < sig["prix"] < sig["objectif"]
    a = s.atr(frame(path_down_then_up(60)[:i]), 14).iloc[-1]
    assert abs((sig["prix"] - sig["stop"]) - 1.5 * a) < 1e-9          # SL à 1,5 ATR
    assert abs((sig["objectif"] - sig["prix"]) - 1.5 * a) < 1e-9      # TP à 1,5 ATR


def test_ancien_calcul_sl_tp_bougies():
    p = dict(P, sl_tp_mode="bougies")
    close = path_down_then_up(60)
    for i in range(80, len(close) + 1):
        sig = s.detect(frame(close[:i]), p)
        if sig:
            break
    assert sig["stop"] == frame(close[:i])["low"].iloc[-10:].min()     # SL = plus bas des 10 dernières bougies
    assert abs((sig["objectif"] - sig["prix"]) - 2 * (sig["prix"] - sig["stop"])) < 1e-9   # TP = 2R


def test_vente_symetrique():
    i, sig = first_signal(220 - path_down_then_up(60))
    assert sig is not None and sig["sens"] == "VENTE" and sig["objectif"] < sig["prix"] < sig["stop"]


def test_un_seul_signal_par_mouvement():
    close = path_down_then_up(60)
    hits = [i for i in range(80, len(close) + 1) if s.detect(frame(close[:i]), P)]
    assert len(hits) == 1                                  # l'alignement ne se « forme » qu'une fois


def test_pas_de_signal_sans_croisement_ni_cassure():
    close = np.concatenate((np.full(60, 100.0), 100 + np.cumsum(np.full(80, 0.05))))   # hausse douce, RSI jamais < 30
    assert first_signal(close)[1] is None


def test_bougie_en_cours_ignoree():
    raw = [{"epoch": e, "open": 1, "high": 1, "low": 1, "close": 1} for e in (0, 3600, 7200)]
    assert len(s.candles(raw, 3600, now=7200 + 100)) == 2        # la bougie de 7200 n'est pas terminée
    assert len(s.candles(raw, 3600, now=10800)) == 3


def test_bougie_en_cours_gardee_si_on_n_attend_pas_la_cloture():
    raw = [{"epoch": e, "open": 1, "high": 1, "low": 1, "close": 1} for e in (0, 3600, 7200)]
    assert len(s.candles(raw, 3600, now=7200 + 100, en_cours=True)) == 3      # la bougie de 7200 est analysée
    cfg = {"unites": ["M15", "H1"], "attendre_cloture": False}
    assert s.due_units(cfg, {"vu": {"M15": 0, "H1": 0}}, 10 * 3600 + 30) == ["M15", "H1"]   # à chaque passage


def test_signal_avant_la_cloture():
    close = path_down_then_up(60)
    i, _ = first_signal(close)
    df = frame(close[:i])                                   # la bougie du signal est la dernière...
    now = float(df["epoch"].iloc[-1]) + 1800                # ... et elle n'est pas finie (H1, à mi-chemin)
    s._fetch_all = lambda r: {("X", 3600): df.to_dict("records")}
    s.asyncio.run = lambda x: x
    cfg = dict(P, marches={"Test": "X"}, unites=["H1"], unites_marche={})
    found = s.run_once(dict(cfg, attendre_cloture=False), {}, send=False, now=now)
    assert len(found) == 1 and found[0][2]["sens"] == "ACHAT"            # signal envoyé pendant la bougie
    assert s.run_once(dict(cfg, attendre_cloture=True), {}, send=False, now=now) == []   # sinon : attend la clôture


def test_unites_a_traiter():
    cfg = {"unites": ["M15", "H1"]}
    now = 10 * 3600 + 30
    assert s.due_units(cfg, {}, now) == ["M15", "H1"]
    st = {"vu": {"M15": 10 * 3600 - 900, "H1": 9 * 3600}}
    assert s.due_units(cfg, st, now) == []
    assert s.due_units(cfg, st, now + 900) == ["M15"]           # 15 min plus tard : seulement M15


def test_m15_seulement_pour_l_or():
    assert s.market_units(P, "Or") == ["M15", "M30", "H1", "H4"]
    assert s.market_units(P, "Volatility 75") == ["M30", "H1", "H4"]
    assert s.all_units(P) == ["M15", "M30", "H1", "H4"]
    reqs = []
    s._fetch_all = lambda r: reqs.extend(r) or {}
    s.asyncio.run = lambda x: x
    s.run_once(dict(P), {}, send=False, units=["M15"], now=10 * 3600 + 30)
    assert reqs == [("frxXAUUSD", 900)]                        # en M15, seul l'or est demandé à Deriv


def test_message_lisible():
    t, m = s.message("EUR/USD", "H1", {"sens": "ACHAT", "prix": 1.11654, "stop": 1.1141, "objectif": 1.12142,
                                        "rsi": 61.2, "epoch": 0})
    assert t == "ACHAT EUR/USD (H1)" and "SL : 1.11410" in m and "TP : 1.12142" in m


def test_telegram_prioritaire_et_jeton_masque():
    sent = {}
    s._post_json = lambda url, body: sent.update(url=url, body=body) or True
    cfg = dict(P, telegram_token="123:ABC", telegram_chat_id="42", ntfy_canal="x")
    assert s.notify(cfg, "ACHAT EUR/USD (H1)", "Prix : 1", True)
    assert sent["url"].startswith("https://api.telegram.org/bot123:ABC/sendMessage") and sent["body"]["chat_id"] == "42"
    assert s.notify(dict(P, ntfy_canal="x"), "t", "m", False) and sent["body"]["topic"] == "x"   # sans Telegram : ntfy


def test_premier_passage_silencieux_et_secrets_par_variables():
    import os
    st = {}
    calls = []
    s._fetch_all = lambda reqs: calls.append(reqs) or {}
    s.asyncio.run = lambda x: x                      # _fetch_all remplacé : pas de réseau
    found = s.run_once(dict(P), st, send=False, now=10 * 3600 + 30, first_silent=True)
    assert found == [] and set(st["vu"]) == set(s.all_units(P))     # première fois : noté, rien envoyé
    os.environ["TELEGRAM_TOKEN"], os.environ["TELEGRAM_CHAT_ID"] = "1:X", "7"
    try:
        cfg = s.load_config()
        assert cfg["telegram_token"] == "1:X" and cfg["telegram_chat_id"] == "7"
        assert "1:X" not in s.CONFIG.read_text(encoding="utf-8")   # le secret n'est jamais écrit sur disque
    finally:
        del os.environ["TELEGRAM_TOKEN"], os.environ["TELEGRAM_CHAT_ID"]


def test_croisement_8_21_puis_cassure_de_la_50():
    i, sig = first_signal(path_down_then_up(60))
    assert sig["croisement_il_y_a"] >= 1                 # le croisement 8/21 a eu lieu AVANT la cassure de la MM50
    assert sig["rsi_confirme"] and sig["rsi_extreme"] <= 35       # la baisse a mis le RSI en survente : confirmé


def test_rsi_confirmation_ou_obligation():
    # remontée sans survente préalable : signal quand même, mais « non confirmé » ; refusé si le RSI est obligatoire
    close = np.concatenate((np.full(40, 105.0), np.linspace(105, 100, 60), 100 + np.cumsum(np.full(60, 0.6))))
    close[40:100] += np.where(np.arange(60) % 2, 0.35, -0.35)          # baisse hachée : le RSI ne va pas jusqu'à 35
    i, sig = first_signal(close)
    assert sig is not None and sig["sens"] == "ACHAT" and not sig["rsi_confirme"]
    old = P["rsi_obligatoire"]
    P["rsi_obligatoire"] = True
    try:
        assert first_signal(close)[1] is None
    finally:
        P["rsi_obligatoire"] = old


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
