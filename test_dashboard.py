"""Tests du tableau de bord : sécurité (jeton, Host), réglages, démarrage/arrêt du bot. python test_dashboard.py"""
import json
import tempfile
import threading
import time
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

import dashboard

PORT = 8799
dashboard.ALLOWED_HOSTS = {f"127.0.0.1:{PORT}", f"localhost:{PORT}"}
tmp = Path(tempfile.mkdtemp()) / "settings.json"
dashboard.SETTINGS = tmp                      # on n'écrit jamais dans le vrai settings.json
dashboard.PROFILES = Path(tempfile.mkdtemp()) / "accounts.json"      # ni dans le vrai accounts.json
srv = ThreadingHTTPServer(("127.0.0.1", PORT), dashboard.Handler)
threading.Thread(target=srv.serve_forever, daemon=True).start()
BASE = f"http://127.0.0.1:{PORT}"


def call(path, body=None, token=dashboard.TOKEN, host=None):
    req = urllib.request.Request(BASE + path, data=None if body is None else json.dumps(body).encode(),
                                 method="GET" if body is None else "POST")
    if token is not None:
        req.add_header("X-Token", token)
    if host:
        req.add_header("Host", host)
    if body is not None:
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            return r.status, r.read().decode("utf-8")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8")


def test_page_servie_avec_le_jeton():
    code, html = call("/", token=None)
    assert code == 200 and dashboard.TOKEN in html and "__TOKEN__" not in html


def test_mauvais_host_refuse():          # protection contre le « DNS rebinding »
    assert call("/", token=None, host="evil.example")[0] == 403
    assert call("/api/status", host="evil.example")[0] == 403


def test_api_sans_jeton_refusee():
    assert call("/api/status", token=None)[0] == 403
    assert call("/api/status", token="mauvais")[0] == 403
    assert call("/api/log?after=0", token=None)[0] == 403
    assert call("/api/start", {"trade": True, "confirm": True}, token=None)[0] == 403
    assert call("/api/stop", {}, token=None)[0] == 403
    assert call("/api/settings", {"RISK_PCT": 1}, token=None)[0] == 403


def test_statut_et_journal():
    code, txt = call("/api/status")
    s = json.loads(txt)
    assert code == 200 and {"bot", "settings", "positions", "sim_capital", "mt5"} <= set(s)
    assert s["settings"]["MAX_POSITIONS"] >= 1
    assert json.loads(call("/api/log?after=0")[1])["lines"] is not None


def test_trader_exige_une_confirmation():
    code, txt = call("/api/start", {"trade": True})
    assert code == 400 and "confirmation" in json.loads(txt)["error"]
    assert call("/api/start", {"trade": True, "confirm": "oui"})[0] == 400      # seulement true (booléen)


def test_reglages_valides_enregistres():
    code, txt = call("/api/settings", {"CAPITAL_CAP": "250", "RISK_PCT": "0,5", "MAX_POSITIONS": 2})
    assert code == 200, txt
    saved = json.loads(tmp.read_text(encoding="utf-8"))
    assert saved == {"CAPITAL_CAP": 250.0, "RISK_PCT": 0.5, "MAX_POSITIONS": 2}, saved
    code, _ = call("/api/settings", {"CAPITAL_CAP": ""})
    assert code == 200 and json.loads(tmp.read_text(encoding="utf-8"))["CAPITAL_CAP"] is None


def test_reglages_invalides_refuses():
    tmp.unlink(missing_ok=True)
    for bad in ({"RISK_PCT": 99}, {"MAX_POSITIONS": 0}, {"RISK_PCT": "abc"}, {"MAX_SPREAD_R": -1}):
        code, _ = call("/api/settings", bad)
        assert code == 400 and not tmp.exists(), bad


def test_connexion_exige_le_jeton():
    for path, body in (("/api/connect", {"login": "123", "password": "x", "server": "S"}),
                       ("/api/connect", {"use_current": True}), ("/api/disconnect", {}),
                       ("/api/accounts/forget", {"login": "123"})):
        assert call(path, body, token=None)[0] == 403, path
        assert call(path, body, host="evil.example")[0] == 403, path


def test_connexion_valide_les_champs_avant_de_toucher_mt5():
    if dashboard.bot.running():
        print("      (ignoré : un bot tourne déjà sur ce PC, la connexion est refusée avec 409)")
        return
    cases = [({"login": "abc", "password": "x", "server": "Deriv-Demo"}, "invalide"),     # numéro non numérique
             ({"login": "123", "server": "Deriv-Demo"}, "Mot de passe"),                 # mot de passe absent
             ({"login": "123", "password": "", "server": "Deriv-Demo"}, "Mot de passe"),
             ({"login": "123", "password": 12345, "server": "Deriv-Demo"}, "Mot de passe"),
             ({"login": "123", "password": "x", "server": "bad;server"}, "serveur"),     # caractères interdits
             ({"login": "1" * 13, "password": "x", "server": "Deriv-Demo"}, "invalide")]
    for body, word in cases:
        dashboard.session["last_connect"] = 0
        code, txt = call("/api/connect", body)
        assert code == 400 and word.lower() in json.loads(txt)["error"].lower(), (body, code, txt)


def test_comptes_memorises_sans_mot_de_passe():
    dashboard.remember_profile(111222, "Deriv-Demo", True)
    dashboard.remember_profile(333444, "Deriv-Server", False)
    raw = dashboard.PROFILES.read_text(encoding="utf-8")
    assert "password" not in raw.lower() and "mot" not in raw.lower()
    s = json.loads(call("/api/status")[1])
    assert [p["login"] for p in s["profiles"]] == [333444, 111222]                       # le plus récent d'abord
    assert call("/api/accounts/forget", {"login": "333444"})[0] == 200
    assert [p["login"] for p in json.loads(call("/api/status")[1])["profiles"]] == [111222]


def test_changement_de_compte_refuse_si_le_bot_tourne():
    real = dashboard.bot.running
    dashboard.bot.running = lambda: True            # on simule un bot en marche (sans en lancer un)
    try:
        for path, body in (("/api/connect", {"use_current": True}), ("/api/disconnect", {})):
            code, txt = call(path, body)
            assert code == 409 and "bot" in json.loads(txt)["error"].lower(), (path, code, txt)
    finally:
        dashboard.bot.running = real


def test_demarrage_arret_du_bot_en_essai_a_blanc():
    if dashboard.bot.running():
        print("      (ignoré : un bot tourne déjà sur ce PC)")
        return
    code, txt = call("/api/start", {"trade": False})
    assert code == 200 and json.loads(txt)["ok"], txt
    time.sleep(12)
    lines = json.loads(call("/api/log?after=0")[1])["lines"]
    joined = "\n".join(t for _, t in lines)
    assert "démarrage" in joined and "ESSAI À BLANC" in joined, joined[:500]
    assert json.loads(call("/api/status")[1])["bot"]["running"] is True
    assert json.loads(call("/api/start", {"trade": False})[1])["ok"] is False        # pas de 2e bot
    assert json.loads(call("/api/stop", {})[1])["ok"] is True
    for _ in range(40):
        if not dashboard.bot.running():
            break
        time.sleep(0.5)
    assert not dashboard.bot.running()


if __name__ == "__main__":
    failed = 0
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            try:
                fn()
                print("OK   ", name)
            except Exception as e:  # noqa: BLE001
                failed += 1
                print("ÉCHEC", name, "->", repr(e)[:300])
    srv.shutdown()
    print("\n" + ("TOUS LES TESTS PASSENT" if not failed else f"{failed} TEST(S) EN ÉCHEC"))
    raise SystemExit(1 if failed else 0)
