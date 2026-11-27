"""Prise de position automatique sur Deriv (contrats Multipliers), à partir des signaux de signaux.py.

Le SL et le TP gardent EXACTEMENT les niveaux de prix du message (1,5 ATR) : on les convertit en montants en
dollars, seule unité acceptée par Deriv pour les Multipliers, puis on vérifie avant d'acheter que les niveaux
renvoyés par Deriv tombent bien sur ceux du message.

Taille : la perte au SL (commission comprise) vaut `risque` du solde (2 %). Si les minimums de Deriv (mise,
SL ou TP à 0,10 $) obligent à risquer plus, on accepte jusqu'à `risque_max` (3 %), au-delà le trade est sauté.
Au plus `positions_max` positions ouvertes par compte, jamais deux sur le même marché.

Comptes (jamais écrits sur disque, jamais affichés) : variables d'environnement
  DERIV_APP_ID   identifiant d'application (developers.deriv.com, type PAT)
  DERIV_COMPTES  JSON : [{"nom": "demo", "compte": "DOT...", "jeton": "<jeton personnel, droit trade>"}, ...]
"""
import asyncio
import json
import logging
import math
import os
import urllib.request

import websockets

log = logging.getLogger("signaux")
API = "https://api.derivws.com/trading/v1/options"
WS_PUBLIC = "wss://api.derivws.com/trading/v1/options/ws/public"


def comptes() -> list[dict]:
    try:
        lst = json.loads(os.environ.get("DERIV_COMPTES", "") or "[]")
    except json.JSONDecodeError:
        log.error("DERIV_COMPTES n'est pas un JSON valide : aucun trade automatique")
        return []
    return [c for c in lst if c.get("compte") and c.get("jeton")]


def _otp_url(compte: dict) -> str:
    """URL WebSocket authentifiée (démo ou réel selon le compte), valable 120 s et une seule fois."""
    req = urllib.request.Request(f"{API}/accounts/{compte['compte']}/otp", data=b"", method="POST", headers={
        "Authorization": f"Bearer {compte['jeton']}", "Deriv-App-ID": os.environ.get("DERIV_APP_ID", ""),
        "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.loads(r.read().decode("utf-8"))["data"]["url"]


class Session:
    def __init__(self, ws):
        self.ws, self.n = ws, 0

    async def ask(self, msg: dict) -> dict:
        self.n += 1
        msg = dict(msg, req_id=self.n)
        await self.ws.send(json.dumps(msg))
        while True:
            r = json.loads(await asyncio.wait_for(self.ws.recv(), 30))
            if r.get("req_id") == self.n:
                return r


def _proposal(sig: dict, symbol: str, currency: str, stake: float, mult: float, sl_amt=None, tp_amt=None) -> dict:
    p = {"proposal": 1, "amount": round(stake, 2), "basis": "stake", "currency": currency, "underlying_symbol": symbol,
         "contract_type": "MULTUP" if sig["sens"] == "ACHAT" else "MULTDOWN", "multiplier": mult}
    if sl_amt is not None:
        p["limit_order"] = {"stop_loss": round(sl_amt, 2), "take_profit": round(tp_amt, 2)}
    return p


def taille(spot: float, side: int, sl: float, tp: float, solde: float, comm_rate: float, mults: list, mise_min: float,
           ordre_min: float, risque: float, risque_max: float) -> dict | str:
    """Mise et multiplicateur pour que la perte au SL (commission comprise) vaille `risque` du solde.
    Renvoie un dict (mise, mult, sl_amt, tp_amt, risque_pct) ou un texte expliquant pourquoi le trade est sauté."""
    d_sl, d_tp = (spot - sl) * side / spot, (tp - spot) * side / spot          # distances relatives au prix actuel
    if d_sl <= 0 or d_tp <= 0:
        return "le prix a déjà dépassé le SL ou le TP"
    cible = solde * risque
    best = None
    for mult in sorted(mults, reverse=True):                     # gros multiplicateur = petite mise bloquée
        notion = cible / (d_sl + comm_rate)                       # mise x multiplicateur visé
        mise = max(notion / mult, mise_min)
        mise = math.ceil(mise * 100) / 100
        n = mise * mult
        sl_amt, tp_amt = n * d_sl + n * comm_rate, n * d_tp - n * comm_rate
        if tp_amt < ordre_min or sl_amt < ordre_min:              # minimums de Deriv : on grossit la position
            k = max(ordre_min / max(tp_amt, 1e-12), ordre_min / max(sl_amt, 1e-12))
            mise = math.ceil(mise * k * 100) / 100
            n = mise * mult
            sl_amt, tp_amt = n * d_sl + n * comm_rate, n * d_tp - n * comm_rate
        if sl_amt >= mise:                                        # le SL doit être touché avant le stop out
            continue
        cand = dict(mise=mise, mult=mult, sl_amt=sl_amt, tp_amt=tp_amt, risque_pct=sl_amt / solde)
        if best is None or abs(cand["risque_pct"] - risque) < abs(best["risque_pct"] - risque):
            best = cand
    if best is None:
        return "aucun multiplicateur ne place le SL avant le stop out"
    if best["risque_pct"] > risque_max + 1e-9:
        return f"minimums Deriv : risque de {best['risque_pct'] * 100:.1f} % (> {risque_max * 100:g} %)"
    return best


async def _preparer(s: Session, sig: dict, symbol: str, currency: str, solde: float, p: dict) -> dict | str:
    """Calcule la taille puis demande un prix à Deriv avec SL/TP, et vérifie les niveaux renvoyés."""
    r = await s.ask({"contracts_for": symbol})
    mults = next((c.get("multiplier_range") for c in r.get("contracts_for", {}).get("available", [])
                  if c.get("contract_type") in ("MULTUP", "MULTDOWN")), None)
    if not mults:
        return "Multipliers indisponibles sur ce marché"
    side = 1 if sig["sens"] == "ACHAT" else -1
    r = await s.ask(_proposal(sig, symbol, currency, 1.0, min(mults)))             # prix et frais actuels
    if "error" in r:
        return f"Deriv : {r['error'].get('message')}"
    pr = r["proposal"]
    spot, vp = float(pr["spot"]), pr.get("validation_params", {})
    mise_min = float(vp.get("stake", {}).get("min", 1))
    ordre_min = max(float(vp.get(k, {}).get("min", 0.1)) for k in ("stop_loss", "take_profit"))
    comm_rate = float(pr.get("commission", 0)) / (1.0 * min(mults))
    t = taille(spot, side, sig["stop"], sig["objectif"], solde, comm_rate, mults, mise_min, ordre_min,
               p["risque"], p["risque_max"])
    if isinstance(t, str):
        return t
    r = await s.ask(_proposal(sig, symbol, currency, t["mise"], t["mult"], t["sl_amt"], t["tp_amt"]))
    if "error" in r:
        return f"Deriv : {r['error'].get('message')}"
    pr = r["proposal"]
    lo = pr.get("limit_order", {})
    sl_px, tp_px = float(lo["stop_loss"]["value"]), float(lo["take_profit"]["value"])
    dist = abs(sig["prix"] - sig["stop"])
    if abs(sl_px - sig["stop"]) > dist * 0.05 or abs(tp_px - sig["objectif"]) > dist * 0.05:   # niveaux décalés
        return f"niveaux Deriv trop éloignés du message (SL {sl_px}, TP {tp_px})"
    return dict(t, id=pr["id"], ask=float(pr["ask_price"]), sl_px=sl_px, tp_px=tp_px, spot=float(pr["spot"]))


async def _compte(compte: dict, signaux: list, cfg: dict, p: dict, achat: bool) -> list[str]:
    """Traite les signaux pour un compte. achat=False : calcule sans acheter (connexion publique, solde fictif)."""
    out = []
    url = await asyncio.to_thread(_otp_url, compte) if achat else WS_PUBLIC
    async with websockets.connect(url, open_timeout=20, close_timeout=5) as ws:
        s = Session(ws)
        if achat:
            b = (await s.ask({"balance": 1}))["balance"]
            solde, currency = float(b["balance"]), b["currency"]
            port = (await s.ask({"portfolio": 1})).get("portfolio", {}).get("contracts", [])
            ouverts = {c.get("underlying_symbol") or c.get("symbol") for c in port}
        else:
            solde, currency, ouverts = float(compte.get("solde", 10)), "USD", set()
        nb = len(ouverts)
        for name, tf, sig in signaux:
            symbol = cfg["marches"][name]
            if nb >= p["positions_max"]:
                out.append(f"{sig['sens']} {name} ({tf}) non pris : {nb} positions déjà ouvertes")
                continue
            if symbol in ouverts:
                out.append(f"{sig['sens']} {name} ({tf}) non pris : position déjà ouverte sur ce marché")
                continue
            prep = await _preparer(s, sig, symbol, currency, solde, p)
            if isinstance(prep, str):
                out.append(f"{sig['sens']} {name} ({tf}) non pris : {prep}")
                continue
            detail = (f"mise {prep['mise']:.2f} {currency} x{prep['mult']:g}, risque {prep['sl_amt']:.2f} "
                      f"({prep['risque_pct'] * 100:.1f} %), SL {prep['sl_px']}, TP {prep['tp_px']}")
            if not achat:
                out.append(f"{sig['sens']} {name} ({tf}) [essai, pas d'achat] : {detail}")
                continue
            r = await s.ask({"buy": prep["id"], "price": prep["ask"]})
            if "error" in r:
                out.append(f"{sig['sens']} {name} ({tf}) non pris : Deriv : {r['error'].get('message')}")
                continue
            nb += 1
            ouverts.add(symbol)
            out.append(f"{sig['sens']} {name} ({tf}) PRIS : {detail}")
    return out


def executer(signaux: list, cfg: dict, achat: bool = True, comptes_essai: list | None = None) -> dict:
    """signaux : liste (nom, unité, sig) des NOUVEAUX signaux. Renvoie {nom du compte: [lignes de compte rendu]}."""
    p = cfg["trading_auto"]
    signaux = [x for x in signaux if x[1] in p["unites"]]
    lst = comptes_essai if comptes_essai is not None else comptes()
    if not signaux or not lst or not p.get("actif"):
        return {}
    res = {}
    for c in lst:
        nom = c.get("nom") or "compte"
        try:
            res[nom] = asyncio.run(_compte(c, signaux, cfg, p, achat))
        except Exception as e:  # noqa: BLE001
            msg = str(e).replace(c.get("jeton", "") or "<aucun>", "***")
            res[nom] = [f"erreur, aucun trade sur ce compte : {msg[:200]}"]
    return res
