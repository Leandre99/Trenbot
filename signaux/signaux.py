"""Bot de SIGNAUX : il ne prend aucune position. Il surveille les marchés et t'envoie une notification sur ton
téléphone (application gratuite ntfy) quand ta stratégie donne un signal. C'est toi qui décides de trader.

Stratégie (à la clôture de chaque bougie, sur chaque marché et chaque unité de temps choisis) :
  ACHAT : le RSI 14 est passé sous 30 (survente) dans les dernières bougies, puis la MM8 passe au-dessus de la MM21,
          les deux au-dessus de la MM50, et le prix clôture au-dessus de la MM50.
  VENTE : l'inverse (RSI au-dessus de 70, MM8 sous la MM21, les deux sous la MM50, prix sous la MM50).
  La notification propose un stop (dernier creux / sommet) et un objectif (2 fois le risque) : à toi de juger.

Données : API publique de Deriv (aucun compte, aucun mot de passe). Pas besoin de MT5 ni de ton PC.
Réglages : config.json (créé au premier lancement, à côté de ce fichier).

    python signaux.py               # tourne en continu
    python signaux.py --once        # un seul passage (affiche ce qu'il voit)
    python signaux.py --test        # envoie une notification d'essai sur ton téléphone
    python signaux.py --sans-notif  # n'envoie rien, affiche seulement
"""
import argparse
import asyncio
import json
import logging
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
    "marches": {"EUR/USD": "frxEURUSD", "GBP/USD": "frxGBPUSD", "USD/JPY": "frxUSDJPY", "USD/CHF": "frxUSDCHF",
                "USD/CAD": "frxUSDCAD", "AUD/USD": "frxAUDUSD", "NZD/USD": "frxNZDUSD", "Or": "frxXAUUSD",
                "Volatility 75": "R_75", "Volatility 100": "R_100", "Step Index": "stpRNG"},
    "unites": ["M15", "H1", "H4"],          # au choix : M1 M5 M15 M30 H1 H4 D1
    "ntfy_serveur": "https://ntfy.sh",
    "ntfy_canal": "",                        # créé au hasard au premier lancement : c'est ton canal privé
    "mm_rapide": 8, "mm_moyenne": 21, "mm_lente": 50,
    "rsi_periode": 14, "rsi_bas": 30, "rsi_haut": 70,
    "rsi_memoire": 20,                       # la survente / le surachat doit dater de moins de N bougies
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
    """Signal sur la DERNIÈRE bougie terminée de df, ou None."""
    need = p["mm_lente"] + p["rsi_memoire"] + 2
    if len(df) < need:
        return None
    c = df["close"]
    f, m, s = (c.rolling(p[k]).mean() for k in ("mm_rapide", "mm_moyenne", "mm_lente"))
    r = rsi(c, p["rsi_periode"])
    up = (f > m) & (m > s) & (c > s)
    dn = (f < m) & (m < s) & (c < s)
    recent = r.iloc[-p["rsi_memoire"]:]
    price = float(c.iloc[-1])
    if up.iloc[-1] and not up.iloc[-2] and recent.min() < p["rsi_bas"]:
        stop = float(df["low"].iloc[-p["stop_bougies"]:].min())
        side = 1
    elif dn.iloc[-1] and not dn.iloc[-2] and recent.max() > p["rsi_haut"]:
        stop = float(df["high"].iloc[-p["stop_bougies"]:].max())
        side = -1
    else:
        return None
    risk = (price - stop) * side
    if risk <= 0:
        return None
    target = price + side * p["objectif_r"] * risk if p["objectif_r"] > 0 else None
    return {"sens": "ACHAT" if side > 0 else "VENTE", "prix": price, "stop": stop, "objectif": target,
            "rsi": float(r.iloc[-1]), "epoch": int(df["epoch"].iloc[-1])}


def fmt_price(x: float) -> str:
    return f"{x:.5f}" if x < 10 else f"{x:.3f}" if x < 1000 else f"{x:.2f}"


def message(name: str, tf: str, sig: dict) -> tuple[str, str]:
    title = f"{sig['sens']} {name} ({tf})"
    lines = [f"Prix : {fmt_price(sig['prix'])}", f"Stop proposé : {fmt_price(sig['stop'])}"]
    if sig["objectif"] is not None:
        lines.append(f"Objectif proposé : {fmt_price(sig['objectif'])}")
    lines.append(f"RSI : {sig['rsi']:.0f}")
    t = time.strftime("%d/%m %H:%M UTC", time.gmtime(sig["epoch"] + GRAN[tf]))
    lines.append(f"Bougie fermée à {t}")
    return title, "\n".join(lines)


# ------------------------------------------------------------------ notification
def notify(cfg: dict, title: str, text: str, buy: bool | None = None) -> bool:
    body = {"topic": cfg["ntfy_canal"], "title": title, "message": text, "priority": 4,
            "tags": ["chart_with_upwards_trend" if buy else "chart_with_downwards_trend"] if buy is not None else ["bell"]}
    req = urllib.request.Request(cfg["ntfy_serveur"].rstrip("/"), data=json.dumps(body).encode("utf-8"),
                                 headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            return r.status == 200
    except Exception as e:  # noqa: BLE001
        log.error("notification non envoyée : %r", e)
        return False


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


def run_once(cfg: dict, st: dict, send: bool, units: list[str] | None = None, now: float | None = None) -> list:
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
    ap.add_argument("--sans-notif", action="store_true", help="n'envoie rien, affiche seulement")
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s",
                        handlers=[logging.StreamHandler(sys.stdout),
                                  logging.FileHandler(HERE / "signaux.log", encoding="utf-8")])
    cfg = load_config()
    log.info("Canal ntfy : %s  (abonne-toi à ce nom dans l'application ntfy)", cfg["ntfy_canal"])
    log.info("Marchés : %s | unités : %s", ", ".join(cfg["marches"]), ", ".join(cfg["unites"]))
    if args.test:
        ok = notify(cfg, "Essai trendbot", "Si tu lis ceci, les signaux arriveront bien sur ton téléphone.")
        log.info("notification d'essai : %s", "envoyée" if ok else "ÉCHEC")
        return
    st = load_state()
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
