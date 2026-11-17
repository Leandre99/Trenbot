"""Bot de SIGNAUX : il ne prend aucune position. Il surveille les marchés et t'envoie une notification sur ton
téléphone (Telegram, ou l'application gratuite ntfy) quand ta stratégie donne un signal. C'est toi qui décides de trader.

Stratégie (à la clôture de chaque bougie, sur chaque marché et chaque unité de temps choisis) :
  ACHAT : la MM8 croise la MM21 vers le haut, puis la MM8, la MM21 et le prix cassent la MM50 vers le haut (signal à
          cette cassure). Le RSI 14 confirme s'il a touché ou frôlé 30 avant ; ce n'est pas obligatoire (indiqué dans le message).
  VENTE : l'inverse (croisement vers le bas, cassure de la MM50 vers le bas, RSI vers 70).
  La notification propose un stop (dernier creux / sommet) et un objectif (2 fois le risque) : à toi de juger.

Données : API publique de Deriv (aucun compte, aucun mot de passe). Pas besoin de MT5 ni de ton PC.
Réglages : config.json (créé au premier lancement, à côté de ce fichier).

    python signaux.py               # tourne en continu
    python signaux.py --once        # un seul passage (affiche ce qu'il voit)
    python signaux.py --passage     # un passage avec mémoire (GitHub Actions)
    python signaux.py --test        # envoie une notification d'essai sur ton téléphone
    python signaux.py --telegram    # branche Telegram (jeton de @BotFather)
    python signaux.py --sans-notif  # n'envoie rien, affiche seulement
"""
import argparse
import asyncio
import json
import logging
import os
import secrets
import sys
import time
import urllib.request
from pathlib import Path

import numpy as np
import pandas as pd
import websockets

HERE = Path(__file__).parent
CONFIG = HERE / "config.json"
STATE = HERE / "etat.json"
WS_URL = "wss://api.derivws.com/trading/v1/options/ws/public"
GRAN = {"M1": 60, "M5": 300, "M15": 900, "M30": 1800, "H1": 3600, "H4": 14400, "D1": 86400}
NB_BOUGIES = 200
log = logging.getLogger("signaux")

DEFAULT = {
    # nom affiché -> code Deriv
    "marches": {
        "Or": "frxXAUUSD",
        "Step Index": "stpRNG",
        "Volatility 10": "R_10", "Volatility 25": "R_25", "Volatility 50": "R_50", "Volatility 75": "R_75",
        "Volatility 100": "R_100",
        "Volatility 10 (1s)": "1HZ10V", "Volatility 15 (1s)": "1HZ15V", "Volatility 25 (1s)": "1HZ25V",
        "Volatility 50 (1s)": "1HZ50V", "Volatility 75 (1s)": "1HZ75V", "Volatility 100 (1s)": "1HZ100V",
    },
    # absents de l'API publique de Deriv : CAD/CHF, CAD/JPY, CHF/JPY, Volatility 150 (1s)
    "unites": ["M15", "M30", "H1", "H4"],          # au choix : M1 M5 M15 M30 H1 H4 D1
    "telegram_token": "",                    # jeton donné par @BotFather (reste sur ta machine, jamais sur GitHub)
    "telegram_chat_id": "",                  # rempli tout seul par : python signaux.py --telegram
    "ntfy_serveur": "https://ntfy.sh",
    "ntfy_canal": "",                        # créé au hasard au premier lancement : c'est ton canal privé
    "mm_rapide": 8, "mm_moyenne": 21, "mm_lente": 50,
    "rsi_periode": 14, "rsi_bas": 30, "rsi_haut": 70,
    "rsi_marge": 5,                          # « frôler » : le RSI est descendu sous 30 + 5 (ou monté au-dessus de 70 - 5)
    "rsi_memoire": 50,                       # ... au cours des N dernières bougies
    "rsi_obligatoire": False,                # False : le RSI confirme seulement (indiqué dans le message) ; True : exigé
    "croisement_max": 30,                    # la cassure de la MM50 doit suivre le croisement MM8/MM21 de N bougies au plus
    "stop_bougies": 10,                      # stop proposé : plus bas / plus haut des N dernières bougies
    "objectif_r": 2.0,                       # objectif proposé : N fois la distance au stop (0 = pas d'objectif)
}


# ------------------------------------------------------------------ réglages et mémoire
def load_config() -> dict:
    cfg = dict(DEFAULT)
    if CONFIG.exists():
        cfg.update(json.loads(CONFIG.read_text(encoding="utf-8")))
    if not cfg["ntfy_canal"]:
        cfg["ntfy_canal"] = "signaux-" + secrets.token_hex(6)      # nom difficile à deviner = canal privé
    bad = [u for u in cfg["unites"] if u not in GRAN]
    if bad:
        raise SystemExit(f"Unité(s) de temps inconnue(s) dans config.json : {bad}. Choix : {list(GRAN)}")
    CONFIG.write_text(json.dumps(cfg, indent=1, ensure_ascii=False), encoding="utf-8")
    for key in ("TELEGRAM_TOKEN", "TELEGRAM_CHAT_ID"):      # secrets fournis par GitHub Actions : jamais écrits sur disque
        if os.environ.get(key):
            cfg[key.lower()] = os.environ[key].strip()
    return cfg


def load_state() -> dict:
    try:
        return json.loads(STATE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def save_state(st: dict) -> None:
    STATE.write_text(json.dumps(st), encoding="utf-8")


# ------------------------------------------------------------------ données Deriv
async def _fetch_all(requests: list[tuple[str, int]]) -> dict:
    """Bougies pour plusieurs (code, granularité) sur une seule connexion."""
    out = {}
    async with websockets.connect(WS_URL, open_timeout=20, close_timeout=5) as ws:
        for n, (code, g) in enumerate(requests, start=1):
            await ws.send(json.dumps({"ticks_history": code, "adjust_start_time": 1, "count": NB_BOUGIES,
                                      "end": "latest", "granularity": g, "style": "candles", "req_id": n}))
            while True:
                resp = json.loads(await asyncio.wait_for(ws.recv(), 30))
                if resp.get("req_id") == n:
                    break
            if "error" in resp:
                log.warning("%s : %s", code, resp["error"].get("message"))
                continue
            out[(code, g)] = resp.get("candles", [])
    return out


def candles(raw: list, g: int, now: float) -> pd.DataFrame:
    """Bougies TERMINÉES uniquement (Deriv renvoie aussi la bougie en cours)."""
    df = pd.DataFrame(raw)
    if df.empty:
        return df
    df = df[df["epoch"] + g <= now].copy()
    df[["open", "high", "low", "close"]] = df[["open", "high", "low", "close"]].astype(float)
    return df.reset_index(drop=True)


# ------------------------------------------------------------------ stratégie
def rsi(c: pd.Series, n: int) -> pd.Series:
    d = c.diff()
    up = d.clip(lower=0).ewm(alpha=1 / n, adjust=False).mean()
    dn = (-d.clip(upper=0)).ewm(alpha=1 / n, adjust=False).mean()
    return 100 - 100 / (1 + up / dn.replace(0, np.nan))


def detect(df: pd.DataFrame, p: dict) -> dict | None:
    """Signal sur la DERNIÈRE bougie terminée de df, ou None.
    ACHAT : 1) la MM8 croise la MM21 vers le haut ; 2) ensuite (ou sur la même bougie) la MM8, la MM21 et le prix
    passent au-dessus de la MM50 : c'est la cassure, le signal part à la clôture de cette bougie.
    Le RSI confirme : il a touché ou frôlé 30 avant (survente). VENTE : l'inverse (RSI vers 70)."""
    need = p["mm_lente"] + p["croisement_max"] + 2
    if len(df) < need:
        return None
    c = df["close"]
    f, m, s = (c.rolling(p[k]).mean() for k in ("mm_rapide", "mm_moyenne", "mm_lente"))
    r = rsi(c, p["rsi_periode"])
    n = len(df)

    def last_cross(up: bool) -> int | None:
        """Indice de la bougie du dernier croisement MM8/MM21 dans ce sens, si la MM8 est restée du bon côté depuis."""
        above = (f > m) if up else (f < m)
        if not above.iloc[-1]:
            return None
        k = n - 1
        while k > 0 and above.iloc[k - 1]:
            k -= 1
        return k if k > 0 else None

    side = 0
    for up in (True, False):
        broke = ((f > s) & (m > s) & (c > s)) if up else ((f < s) & (m < s) & (c < s))   # MM8, MM21 et prix de l'autre côté de la MM50
        if not (broke.iloc[-1] and not broke.iloc[-2]):         # la cassure de la MM50 se fait sur CETTE bougie
            continue
        k = last_cross(up)
        if k is None or n - 1 - k > p["croisement_max"]:        # croisement 8/21 trop ancien : ce n'est pas le même mouvement
            continue
        if broke.iloc[k:n - 1].any():                             # déjà cassée depuis ce croisement : un seul signal par croisement
            continue
        side = 1 if up else -1
        break
    if not side:
        return None
    k = last_cross(side > 0)
    window = r.iloc[max(0, k - p["rsi_memoire"]):n]
    if side > 0:
        extreme = float(window.min())
        confirm = extreme <= p["rsi_bas"] + p["rsi_marge"]
    else:
        extreme = float(window.max())
        confirm = extreme >= p["rsi_haut"] - p["rsi_marge"]
    if p["rsi_obligatoire"] and not confirm:
        return None
    price = float(c.iloc[-1])
    stop = float(df["low"].iloc[-p["stop_bougies"]:].min()) if side > 0 else float(df["high"].iloc[-p["stop_bougies"]:].max())
    risk = (price - stop) * side
    if risk <= 0:
        return None
    target = price + side * p["objectif_r"] * risk if p["objectif_r"] > 0 else None
    return {"sens": "ACHAT" if side > 0 else "VENTE", "prix": price, "stop": stop, "objectif": target,
            "rsi": float(r.iloc[-1]), "rsi_extreme": extreme, "rsi_confirme": bool(confirm),
            "croisement_il_y_a": n - 1 - k, "epoch": int(df["epoch"].iloc[-1])}


def fmt_price(x: float) -> str:
    return f"{x:.5f}" if x < 10 else f"{x:.3f}" if x < 1000 else f"{x:.2f}"


def message(name: str, tf: str, sig: dict) -> tuple[str, str]:
    """Message court : sens, marché et unité en titre, puis prix, stop et objectif."""
    title = f"{sig['sens']} {name} ({tf})"
    lines = [f"Prix : {fmt_price(sig['prix'])}", f"Stop proposé : {fmt_price(sig['stop'])}"]
    if sig["objectif"] is not None:
        lines.append(f"Objectif proposé : {fmt_price(sig['objectif'])}")
    return title, "\n".join(lines)


# ------------------------------------------------------------------ notification
def _post_json(url: str, body: dict) -> bool:
    req = urllib.request.Request(url, data=json.dumps(body).encode("utf-8"),
                                 headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            return r.status == 200
    except Exception as e:  # noqa: BLE001
        log.error("notification non envoyée : %s", str(e).replace(cfg_token(), "***"))
        return False


_TOKEN = {"v": ""}          # jeton Telegram, masqué dans les messages d'erreur


def cfg_token() -> str:
    return _TOKEN["v"] or "<aucun>"


def notify(cfg: dict, title: str, text: str, buy: bool | None = None) -> bool:
    """Telegram si configuré, sinon ntfy."""
    if cfg.get("telegram_token") and cfg.get("telegram_chat_id"):
        _TOKEN["v"] = cfg["telegram_token"]
        icon = "🟢" if buy else "🔴" if buy is not None else "🔔"
        return _post_json(f"https://api.telegram.org/bot{cfg['telegram_token']}/sendMessage",
                          {"chat_id": cfg["telegram_chat_id"], "text": f"{icon} {title}\n{text}"})
    return _notify_ntfy(cfg, title, text, buy)


def telegram_setup(cfg: dict) -> None:
    """Trouve l'identifiant de ta discussion avec ton bot (envoie-lui d'abord un message) et l'enregistre."""
    tok = cfg.get("telegram_token", "").strip()
    if not tok:
        tok = input("Colle le jeton donné par @BotFather : ").strip()
    try:
        with urllib.request.urlopen(f"https://api.telegram.org/bot{tok}/getUpdates", timeout=20) as r:
            upd = json.loads(r.read().decode("utf-8"))
    except Exception:  # noqa: BLE001
        raise SystemExit("Jeton refusé par Telegram : vérifie-le (copie-colle exacte depuis @BotFather).")
    chats = [u[k]["chat"]["id"] for u in upd.get("result", []) for k in ("message", "edited_message") if k in u]
    if not chats:
        raise SystemExit("Aucun message reçu : ouvre ton bot dans Telegram, appuie sur Démarrer (ou écris « salut »), puis relance.")
    cfg["telegram_token"], cfg["telegram_chat_id"] = tok, str(chats[-1])
    CONFIG.write_text(json.dumps(cfg, indent=1, ensure_ascii=False), encoding="utf-8")
    ok = notify(cfg, "Essai trendbot", "Telegram est branché : les signaux arriveront ici.")
    print("Telegram branché, message d'essai :", "envoyé" if ok else "ÉCHEC")


def _notify_ntfy(cfg: dict, title: str, text: str, buy: bool | None = None) -> bool:
    body = {"topic": cfg["ntfy_canal"], "title": title, "message": text, "priority": 4,
            "tags": ["chart_with_upwards_trend" if buy else "chart_with_downwards_trend"] if buy is not None else ["bell"]}
    return _post_json(cfg["ntfy_serveur"].rstrip("/"), body)


# ------------------------------------------------------------------ un passage
def due_units(cfg: dict, st: dict, now: float) -> list[str]:
    """Unités dont une bougie vient de se terminer depuis le dernier passage."""
    due = []
    for tf in cfg["unites"]:
        g = GRAN[tf]
        last_open = (int(now) // g) * g - g          # ouverture de la dernière bougie terminée
        if st.get("vu", {}).get(tf) != last_open:
            due.append(tf)
    return due


def run_once(cfg: dict, st: dict, send: bool, units: list[str] | None = None, now: float | None = None,
             first_silent: bool = False) -> list:
    """first_silent : la toute première fois qu'une unité est vue, on la note sans envoyer
    (évite d'envoyer un vieux signal H4 au premier lancement)."""
    now = time.time() if now is None else now
    units = due_units(cfg, st, now) if units is None else units
    if not units:
        return []
    reqs = [(code, GRAN[tf]) for tf in units for code in cfg["marches"].values()]
    data = asyncio.run(_fetch_all(reqs))
    found = []
    sent = st.setdefault("envoyes", {})
    for tf in units:
        g = GRAN[tf]
        last_open = (int(now) // g) * g - g
        if first_silent and tf not in st.get("vu", {}):
            st.setdefault("vu", {})[tf] = last_open
            continue
        for name, code in cfg["marches"].items():
            df = candles(data.get((code, g), []), g, now)
            if df.empty:
                continue
            if int(df["epoch"].iloc[-1]) != last_open:      # marché fermé (week-end) : pas de signal périmé
                continue
            sig = detect(df, cfg)
            if sig is None:
                continue
            key = f"{code}|{tf}|{sig['epoch']}"
            if key in sent:
                continue
            title, text = message(name, tf, sig)
            log.info("SIGNAL %s | %s", title, text.replace("\n", " | "))
            ok = notify(cfg, title, text, sig["sens"] == "ACHAT") if send else True
            if ok:
                sent[key] = int(now)
            found.append((name, tf, sig))
        st.setdefault("vu", {})[tf] = last_open
    for k in [k for k, v in sent.items() if now - v > 7 * 86400]:       # on oublie après une semaine
        del sent[k]
    return found


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--once", action="store_true", help="un seul passage sur toutes les unités")
    ap.add_argument("--test", action="store_true", help="envoie une notification d'essai")
    ap.add_argument("--passage", action="store_true", help="un passage avec mémoire (pour GitHub Actions, lancé toutes les 5 min)")
    ap.add_argument("--telegram", action="store_true", help="branche Telegram (jeton de @BotFather)")
    ap.add_argument("--sans-notif", action="store_true", help="n'envoie rien, affiche seulement")
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s",
                        handlers=[logging.StreamHandler(sys.stdout),
                                  logging.FileHandler(HERE / "signaux.log", encoding="utf-8")])
    cfg = load_config()
    if args.telegram:
        telegram_setup(cfg)
        return
    if cfg.get("telegram_token") and cfg.get("telegram_chat_id"):
        log.info("Notifications : Telegram")
    else:
        log.info("Notifications : ntfy, canal %s  (abonne-toi à ce nom dans l'application ntfy)", cfg["ntfy_canal"])
    log.info("Marchés : %s | unités : %s", ", ".join(cfg["marches"]), ", ".join(cfg["unites"]))
    if args.test:
        ok = notify(cfg, "Essai trendbot", "Si tu lis ceci, les signaux arriveront bien sur ton téléphone.")
        log.info("notification d'essai : %s", "envoyée" if ok else "ÉCHEC")
        return
    st = load_state()
    if args.passage:
        found = run_once(cfg, st, not args.sans_notif, first_silent=True)
        save_state(st)
        log.info("passage terminé : %d signal(aux) | bougies vues : %s", len(found), st.get("vu"))
        return
    if args.once:
        found = run_once(cfg, {}, not args.sans_notif, units=cfg["unites"])
        log.info("passage terminé : %d signal(aux)", len(found))
        return
    if not args.sans_notif:
        notify(cfg, "Bot de signaux démarré", f"Unités : {', '.join(cfg['unites'])}\nMarchés : {len(cfg['marches'])}")
    while True:
        try:
            run_once(cfg, st, not args.sans_notif)
            save_state(st)
        except Exception:  # noqa: BLE001
            log.exception("erreur pendant le passage : nouvel essai à la minute suivante")
        time.sleep(60 - time.time() % 60 + 5)        # 5 s après chaque minute pile


if __name__ == "__main__":
    main()
