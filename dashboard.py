"""Tableau de bord web de trendbot : tourne uniquement sur ton PC (http://127.0.0.1:8765).

Lancer : python dashboard.py      (ou double-clic sur lancer_tableau_de_bord.bat)
- connexion / déconnexion / changement de compte MT5
- démarre / arrête le bot (processus à part : fermer la page ne coupe pas tes stop-loss)
- journal en direct, positions, gains du bot, bilan, réglages
Sécurité : écoute uniquement sur 127.0.0.1, vérifie l'en-tête Host, exige un jeton secret (généré à chaque lancement)
pour toute requête /api. Le mot de passe MT5 n'est JAMAIS enregistré ni journalisé : il sert uniquement à l'appel de connexion.
Seuls le numéro de compte et le serveur sont mémorisés (accounts.json) pour les retrouver en un clic.
"""
import argparse
import collections
import json
import os
import re
import secrets
import subprocess
import sys
import threading
import time
import webbrowser
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import config

HERE = Path(__file__).parent
WEB = HERE / "dashboard"
SETTINGS = HERE / "settings.json"
PROFILES = HERE / "accounts.json"
PORT = 8765
TOKEN = secrets.token_urlsafe(24)
ALLOWED_HOSTS = {f"127.0.0.1:{PORT}", f"localhost:{PORT}"}
MAX_BODY = 20_000
FIELDS = {  # clé -> (minimum, maximum, entier ?)
    "CAPITAL_CAP": (1, 10_000_000, False), "RISK_PCT": (0.05, 5, False), "MAX_RISK_PCT": (0.1, 10, False),
    "MAX_POSITIONS": (1, 10, True), "DAILY_LOSS_STOP_PCT": (0.5, 50, False), "MAX_SPREAD_R": (0.01, 1, False),
}

mt5_lock = threading.RLock()                 # un seul thread parle à MT5 à la fois
session = {"manual_disconnect": False, "last_connect": 0.0}
poll_now = threading.Event()                 # réveille tout de suite le thread qui interroge MT5


# ------------------------------------------------------------------ le bot (processus à part)
class Bot:
    def __init__(self):
        self.proc = None
        self.mode = ""
        self.lock = threading.Lock()
        self.lines = collections.deque(maxlen=2500)   # (id, texte)
        self.next_id = 1
        self.started_at = None

    def push(self, text: str):
        with self.lock:
            self.lines.append((self.next_id, text.rstrip("\n")))
            self.next_id += 1

    def _reader(self, p):
        for line in p.stdout:
            self.push(line)
        p.wait()
        self.push(f"--- le bot s'est arrêté (code {p.returncode}) ---")

    def start(self, args: list[str], mode: str) -> bool:
        if self.running():
            return False
        env = dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONUNBUFFERED="1")
        exe = sys.executable.replace("pythonw.exe", "python.exe")
        self.proc = subprocess.Popen([exe, "-u", "live_mt5.py", *args], cwd=HERE, env=env, stdout=subprocess.PIPE,
                                     stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace",
                                     creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        self.mode, self.started_at = mode, time.time()
        self.push(f"=== démarrage : {mode} ===")
        threading.Thread(target=self._reader, args=(self.proc,), daemon=True).start()
        return True

    def own_running(self) -> bool:
        return self.proc is not None and self.proc.poll() is None

    def running(self) -> bool:
        return self.own_running() or self.external() is not None

    _scan = (0.0, None)

    def external(self):
        """PID d'un bot qui trade lancé AILLEURS (ligne de commande, ancienne fenêtre...), sinon None.
        Cherche le fichier verrou du bot, puis (pour les anciennes versions sans verrou) la liste des processus."""
        import live_mt5
        own = self.proc.pid if self.own_running() else None
        pid = live_mt5.trade_lock_pid()
        if pid and pid != own:
            return pid
        if time.time() - Bot._scan[0] > 10:      # balayage des processus, au plus toutes les 10 s
            found = None
            try:
                out = subprocess.run(
                    ["powershell", "-NoProfile", "-Command",
                     "Get-CimInstance Win32_Process -Filter \"Name='python.exe'\" | "
                     "Where-Object { $_.CommandLine -match 'live_mt5\\.py.*--trade' } | "
                     "Select-Object -ExpandProperty ProcessId"],
                    capture_output=True, text=True, timeout=15,
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)).stdout
                pids = [int(x) for x in out.split() if x.isdigit() and int(x) != own]
                found = pids[0] if pids else None
            except Exception:  # noqa: BLE001
                pass
            Bot._scan = (time.time(), found)
        return Bot._scan[1]

    def stop(self) -> bool:
        if not self.running():
            return False
        if self.own_running():
            self.proc.terminate()
        else:
            ext = self.external()
            if ext:
                subprocess.run(["taskkill", "/PID", str(ext), "/T", "/F"], capture_output=True,
                               creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        self.push("=== arrêt demandé (les positions ouvertes gardent leur stop-loss) ===")
        return True

    def since(self, after: int) -> list:
        with self.lock:
            return [[i, t] for i, t in self.lines if i > after]


bot = Bot()
state_lock = threading.Lock()
EMPTY = {"mt5": False, "error": "", "account": None, "positions": [], "bot_pnl": 0.0, "series": [], "summary": None}
STATE: dict = dict(EMPTY, error="MT5 pas encore interrogé")


# ------------------------------------------------------------------ comptes mémorisés (jamais de mot de passe)
def load_profiles() -> list:
    try:
        data = json.loads(PROFILES.read_text(encoding="utf-8"))
        return [p for p in data if isinstance(p, dict) and str(p.get("login", "")).isdigit()]
    except Exception:  # noqa: BLE001
        return []


def remember_profile(login: int, server: str, demo: bool | None = None) -> None:
    items = [p for p in load_profiles() if str(p["login"]) != str(login)]
    items.insert(0, {"login": int(login), "server": server, "demo": demo, "last": int(time.time())})
    PROFILES.write_text(json.dumps(items[:10], indent=1), encoding="utf-8")


def forget_profile(login: str) -> None:
    PROFILES.write_text(json.dumps([p for p in load_profiles() if str(p["login"]) != str(login)], indent=1), encoding="utf-8")


# ------------------------------------------------------------------ connexion / déconnexion MT5
def connect(login: str, password: str, server: str) -> dict:
    """Connecte MT5 à un compte. Le mot de passe n'est ni stocké ni écrit nulle part."""
    import MetaTrader5 as mt5
    with mt5_lock:
        if not mt5.initialize():
            raise RuntimeError("MetaTrader 5 est introuvable ou fermé : ouvre-le puis réessaie.")
        if not mt5.login(int(login), password=password, server=server):
            _, msg = mt5.last_error()
            raise RuntimeError(f"Connexion refusée par le serveur ({msg}). Vérifie le numéro, le mot de passe et le serveur.")
        session["manual_disconnect"] = False
        acc = mt5.account_info()
        demo = acc.trade_mode == mt5.ACCOUNT_TRADE_MODE_DEMO
        remember_profile(acc.login, acc.server, demo)
        return {"login": acc.login, "server": acc.server, "demo": demo}


def use_current() -> dict:
    """Se branche sur le compte déjà ouvert dans MT5 (aucun mot de passe nécessaire)."""
    import MetaTrader5 as mt5
    with mt5_lock:
        if not mt5.initialize():
            raise RuntimeError("MetaTrader 5 est introuvable ou fermé : ouvre-le et connecte-toi à un compte.")
        acc = mt5.account_info()
        if acc is None:
            raise RuntimeError("Aucun compte connecté dans MT5 : connecte-toi d'abord dans MT5.")
        session["manual_disconnect"] = False
        demo = acc.trade_mode == mt5.ACCOUNT_TRADE_MODE_DEMO
        remember_profile(acc.login, acc.server, demo)
        return {"login": acc.login, "server": acc.server, "demo": demo}


def disconnect() -> None:
    """Détache le tableau de bord de MT5 (MT5 lui-même reste ouvert)."""
    import MetaTrader5 as mt5
    with mt5_lock:
        mt5.shutdown()
        session["manual_disconnect"] = True
    with state_lock:
        STATE.update(EMPTY, error="Déconnecté")
    poll_now.set()


# ------------------------------------------------------------------ interrogation de MT5 (un seul thread)
def poll_mt5():
    import MetaTrader5 as mt5
    import live_mt5
    last_deals, last_login = 0.0, None
    while True:
        try:
            if session["manual_disconnect"]:
                poll_now.wait(1.5)
                poll_now.clear()
                continue
            with mt5_lock:
                ti = mt5.terminal_info()
                if ti is None or not ti.connected:
                    if not mt5.initialize():
                        raise RuntimeError("MT5 fermé ou non connecté")
                acc = mt5.account_info()
                if acc is None:
                    raise RuntimeError("Aucun compte connecté dans MT5")
                if acc.login != last_login:                 # nouveau compte : on repart de zéro
                    last_login, last_deals = acc.login, 0.0
                    live_mt5.STATE_FILE = live_mt5.state_path(acc.login)
                    remember_profile(acc.login, acc.server, acc.trade_mode == mt5.ACCOUNT_TRADE_MODE_DEMO)
                    with state_lock:
                        STATE.update(series=[], summary=None, bot_pnl=0.0)
                positions = [{"symbol": p.symbol, "side": "ACHAT" if p.type == mt5.POSITION_TYPE_BUY else "VENTE",
                              "lots": p.volume, "open": p.price_open, "sl": p.sl, "price": p.price_current,
                              "pnl": round(p.profit + p.swap, 2)}
                             for p in (mt5.positions_get() or []) if p.magic == config.MAGIC]
                snap = {"mt5": True, "error": "",
                        "account": {"login": acc.login, "server": acc.server, "currency": acc.currency, "name": acc.name,
                                    "demo": acc.trade_mode == mt5.ACCOUNT_TRADE_MODE_DEMO, "leverage": acc.leverage,
                                    "balance": round(acc.balance, 2), "equity": round(acc.equity, 2),
                                    "margin_free": round(acc.margin_free, 2)},
                        "positions": positions}
                if time.time() - last_deals > 30:
                    last_deals = time.time()
                    now = datetime.now(timezone.utc)
                    deals = [d for d in (mt5.history_deals_get(now - timedelta(days=30), now + timedelta(days=1)) or [])
                             if d.magic == config.MAGIC]
                    trades = {}
                    for d in deals:
                        t = trades.setdefault(d.position_id, {"symbol": d.symbol, "net": 0.0, "out": None})
                        t["net"] += d.profit + d.commission + d.swap + d.fee
                        if d.entry in (mt5.DEAL_ENTRY_OUT, mt5.DEAL_ENTRY_OUT_BY):
                            t["out"] = d.time
                    closed = sorted((t for t in trades.values() if t["out"]), key=lambda t: t["out"])
                    cum, series = 0.0, []
                    for t in closed:
                        cum += t["net"]
                        series.append([t["out"], round(cum, 2)])
                    wins = [t["net"] for t in closed if t["net"] > 0]
                    losses = [t["net"] for t in closed if t["net"] <= 0]
                    by = collections.defaultdict(lambda: [0, 0.0])
                    for t in closed:
                        by[t["symbol"]][0] += 1
                        by[t["symbol"]][1] += t["net"]
                    snap["series"] = series
                    snap["summary"] = {
                        "trades": len(closed), "wins": len(wins), "net": round(cum, 2),
                        "pf": round(sum(wins) / -sum(losses), 2) if losses and sum(losses) < 0 else None,
                        "avg_win": round(sum(wins) / len(wins), 2) if wins else None,
                        "avg_loss": round(sum(losses) / len(losses), 2) if losses else None,
                        "by_market": sorted(([k, v[0], round(v[1], 2)] for k, v in by.items()), key=lambda x: x[2])}
                st = live_mt5.load_state()
                snap["bot_pnl"] = round(live_mt5.bot_pnl(st["sim_start"]), 2) if st.get("sim_start") else 0.0
            with state_lock:
                STATE.update(snap)
        except Exception as e:  # noqa: BLE001
            with state_lock:
                STATE.update(EMPTY, error=str(e))
        poll_now.wait(5)
        poll_now.clear()


def refresh_now(timeout: float = 6.0) -> None:
    """Après une connexion : relit MT5 tout de suite et attend que l'état soit à jour."""
    poll_now.set()
    t0 = time.time()
    while time.time() - t0 < timeout:
        with state_lock:
            if STATE["mt5"] and STATE["account"]:
                return
        time.sleep(0.15)


def status_payload() -> dict:
    import importlib
    importlib.reload(config)
    with state_lock:
        s = dict(STATE)
    cap = config.CAPITAL_CAP
    own = bot.own_running()
    ext = None if own else bot.external()
    s["bot"] = {"running": own or ext is not None,
                "mode": bot.mode if own else ("trade sur la démo (lancé hors du tableau de bord)" if ext else ""),
                "started_at": bot.started_at if own else None}
    s["settings"] = {k: getattr(config, k) for k in FIELDS}
    s["sim_capital"] = round((cap + s["bot_pnl"]) if cap else (s["account"] or {}).get("equity", 0), 2)
    s["disconnected"] = session["manual_disconnect"]
    s["profiles"] = load_profiles()
    s["time"] = time.time()
    return s


def save_settings(data: dict) -> dict:
    out = {}
    for key, (lo, hi, is_int) in FIELDS.items():
        if key not in data:
            continue
        v = data[key]
        if v in (None, "") and key == "CAPITAL_CAP":
            out[key] = None
            continue
        try:
            v = float(str(v).replace(",", "."))
        except ValueError:
            raise ValueError(f"{key} : nombre attendu")
        if not (lo <= v <= hi):
            raise ValueError(f"{key} : doit être entre {lo} et {hi}")
        out[key] = int(v) if is_int else v
    SETTINGS.write_text(json.dumps(out, indent=1), encoding="utf-8")
    return out


# ------------------------------------------------------------------ serveur HTTP
class Handler(BaseHTTPRequestHandler):
    server_version = "trendbot"

    def log_message(self, *a):  # silencieux : on ne journalise jamais les requêtes (elles peuvent contenir un mot de passe)
        pass

    def _host_ok(self) -> bool:
        return self.headers.get("Host", "") in ALLOWED_HOSTS

    def _send(self, code: int, body: bytes, ctype="application/json; charset=utf-8"):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Content-Security-Policy", "default-src 'self'; style-src 'self' 'unsafe-inline'; "
                         "script-src 'self' 'unsafe-inline'; connect-src 'self'; img-src 'self' data:; frame-ancestors 'none'")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, obj, code=200):
        self._send(code, json.dumps(obj, ensure_ascii=False).encode("utf-8"))

    def _authorized(self) -> bool:
        if not self._host_ok():
            return False
        try:
            return secrets.compare_digest(self.headers.get("X-Token", "").encode("utf-8"), TOKEN.encode("utf-8"))
        except Exception:  # noqa: BLE001
            return False

    def do_GET(self):
        u = urlparse(self.path)
        if not self._host_ok():
            return self._send(403, b"forbidden", "text/plain")
        if u.path == "/":
            html = (WEB / "index.html").read_text(encoding="utf-8").replace("__TOKEN__", TOKEN)
            return self._send(200, html.encode("utf-8"), "text/html; charset=utf-8")
        if not self._authorized():
            return self._json({"error": "non autorisé"}, 403)
        if u.path == "/api/status":
            return self._json(status_payload())
        if u.path == "/api/log":
            after = int(parse_qs(u.query).get("after", ["0"])[0])
            return self._json({"lines": bot.since(after)})
        self._json({"error": "introuvable"}, 404)

    def do_POST(self):
        try:                                    # on lit toujours le contenu (borné) avant de répondre : pas de connexion coupée en plein envoi
            n = max(0, int(self.headers.get("Content-Length", "0")))
        except ValueError:
            n = 0
        raw = self.rfile.read(min(n, MAX_BODY))
        if not self._authorized():
            return self._json({"error": "non autorisé"}, 403)
        if n > MAX_BODY:
            return self._json({"error": "requête trop grande"}, 413)
        try:
            data = json.loads(raw or b"{}")
            if not isinstance(data, dict):
                raise ValueError
        except Exception:  # noqa: BLE001
            return self._json({"error": "requête invalide"}, 400)
        path = urlparse(self.path).path

        if path == "/api/start":
            trade = bool(data.get("trade"))
            if trade and data.get("confirm") is not True:
                return self._json({"error": "confirmation requise pour trader"}, 400)
            ok = bot.start(["--trade"] if trade else [], "trade sur la démo" if trade else "essai à blanc")
            return self._json({"ok": ok, "error": "" if ok else "le bot tourne déjà"})
        if path == "/api/stop":
            return self._json({"ok": bot.stop()})
        if path == "/api/settings":
            try:
                return self._json({"ok": True, "saved": save_settings(data)})
            except ValueError as e:
                return self._json({"ok": False, "error": str(e)}, 400)

        if path in ("/api/connect", "/api/disconnect", "/api/accounts/forget"):
            if path == "/api/accounts/forget":
                forget_profile(str(data.get("login", "")))
                return self._json({"ok": True})
            if bot.running():
                return self._json({"ok": False, "error": "Arrête d'abord le bot avant de changer de compte."}, 409)
            if path == "/api/disconnect":
                disconnect()
                return self._json({"ok": True})
            if time.time() - session["last_connect"] < 2:
                return self._json({"ok": False, "error": "Patiente une seconde entre deux tentatives."}, 429)
            session["last_connect"] = time.time()
            try:
                if data.get("use_current"):
                    acc = use_current()
                    refresh_now()
                    return self._json({"ok": True, "account": acc})
                login, pw, server = str(data.get("login", "")).strip(), data.get("password"), str(data.get("server", "")).strip()
                if not re.fullmatch(r"\d{1,12}", login):
                    return self._json({"ok": False, "error": "Numéro de compte invalide (chiffres uniquement)."}, 400)
                if not isinstance(pw, str) or not (1 <= len(pw) <= 200):
                    return self._json({"ok": False, "error": "Mot de passe manquant."}, 400)
                if not re.fullmatch(r"[\w .\-]{1,80}", server):
                    return self._json({"ok": False, "error": "Nom de serveur invalide."}, 400)
                try:
                    acc = connect(login, pw, server)
                finally:
                    pw = None                                  # le mot de passe ne survit pas à l'appel
                refresh_now()
                return self._json({"ok": True, "account": acc})
            except RuntimeError as e:
                return self._json({"ok": False, "error": str(e)}, 400)
        self._json({"error": "introuvable"}, 404)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-browser", action="store_true")
    args = ap.parse_args()
    threading.Thread(target=poll_mt5, daemon=True).start()
    srv = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    url = f"http://127.0.0.1:{PORT}/"
    print(f"Tableau de bord : {url}   (Ctrl+C pour quitter : cela arrête aussi le bot, tes stop-loss restent chez le broker)")
    if not args.no_browser:
        webbrowser.open(url)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        if bot.own_running():
            bot.stop()


if __name__ == "__main__":
    main()
