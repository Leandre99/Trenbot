"""Boucle en direct de la stratégie Drift Switch (règles dans dsi.py).
Lancée par live_mt5.py quand config.STRATEGY == "dsi" : mêmes options (--trade, --once), même journal, même verrou.
Le bot se réveille à chaque minute, 2 s après la clôture de la bougie."""
import logging
import time
from datetime import datetime, timezone

import MetaTrader5 as mt5
import numpy as np

import config
from dsi import DSIParams, decide, stop_distance
from risk import bot_day_halt, lot_for_risk

log = logging.getLogger("bot")
LABEL = "Drift Switch 10"
params = DSIParams(L=config.DSI_L, k=config.DSI_K, stop_mult=config.DSI_STOP_MULT)
_quiet: dict = {}


def closes(symbol: str, n: int):
    """Heures et clôtures des n dernières bougies 1 minute TERMINÉES (position 1 = on saute la bougie en cours)."""
    for _ in range(4):
        r = mt5.copy_rates_from_pos(symbol, mt5.TIMEFRAME_M1, 1, n)
        if r is not None and len(r) >= n * 0.9:
            return r["time"], r["close"].astype(float)
        time.sleep(1)
    return None, None


def day_pnl(symbol: str, lm) -> float:
    """Gain/perte du bot depuis minuit UTC (positions fermées + position ouverte)."""
    now = datetime.now(timezone.utc)
    start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    deals = mt5.history_deals_get(start, now.replace(hour=23, minute=59, second=59)) or []
    realized = sum(d.profit + d.commission + d.swap + d.fee for d in deals if d.magic == config.MAGIC)
    return realized + sum(p.profit + p.swap for p in lm.my_positions())


def close_position(pos, lm, trade: bool, why: str) -> bool:
    tick = mt5.symbol_info_tick(pos.symbol)
    buy = pos.type == mt5.POSITION_TYPE_BUY
    req = {"action": mt5.TRADE_ACTION_DEAL, "symbol": pos.symbol, "volume": pos.volume, "position": pos.ticket,
           "type": mt5.ORDER_TYPE_SELL if buy else mt5.ORDER_TYPE_BUY, "price": tick.bid if buy else tick.ask,
           "deviation": config.DEVIATION, "magic": config.MAGIC, "comment": "trendbot dsi sortie",
           "type_time": mt5.ORDER_TIME_GTC, "type_filling": lm.filling_type(pos.symbol)}
    log.info("%s : SORTIE de %s (%s) | résultat de la position : %+.2f", LABEL, "l'achat" if buy else "la vente", why, pos.profit)
    return lm.send(req, trade, f"SORTIE {pos.symbol} {pos.volume} lots")


def open_position(symbol: str, side: int, c: np.ndarray, m: float, thr: float, lm, trade: bool) -> bool:
    sf = "achat" if side > 0 else "vente"
    acc, info, tick = mt5.account_info(), mt5.symbol_info(symbol), mt5.symbol_info_tick(symbol)
    equity = config.CAPITAL_CAP or acc.equity
    pnl = day_pnl(symbol, lm)
    if bot_day_halt(pnl, equity - pnl, config.DAILY_LOSS_STOP_PCT):
        log.warning("%s : signal %s REFUSÉ : limite de perte du jour atteinte (%.2f)", LABEL, sf, pnl)
        return False
    entry = tick.ask if side > 0 else tick.bid
    spread = tick.ask - tick.bid
    sp_pct = spread / entry * 100
    if sp_pct < config.DSI_MIN_SPREAD_PCT:       # spread serré = phase calme de l'indice : pas de tendance à suivre
        if time.time() - _quiet.get("t", 0) > 600:   # une ligne toutes les 10 min au plus
            _quiet["t"] = time.time()
            log.info("%s : signal %s REFUSÉ : phase calme (spread %.3f %% du prix, il faut au moins %.3f %%)",
                     LABEL, sf, sp_pct, config.DSI_MIN_SPREAD_PCT)
        return False
    if sp_pct > config.DSI_MAX_SPREAD_PCT:
        log.info("%s : signal %s REFUSÉ : spread anormal %.2f = %.3f %% du prix (max %.3f %%)",
                 LABEL, sf, spread, sp_pct, config.DSI_MAX_SPREAD_PCT)
        return False
    dist = float(stop_distance(entry, c, params))
    if not dist > info.trade_stops_level * info.point:
        log.info("%s : signal %s REFUSÉ : stop de sécurité trop proche du prix", LABEL, sf)
        return False
    sl = entry - side * dist
    tv = info.trade_tick_value_loss if info.trade_tick_value_loss > 0 else info.trade_tick_value
    lots = lot_for_risk(equity, config.RISK_PCT, config.MAX_RISK_PCT, entry, sl,
                        info.trade_tick_size, tv, info.volume_min, info.volume_max, info.volume_step)
    if lots.reason:
        log.info("%s : signal %s REFUSÉ : %s", LABEL, sf, lots.reason)
        return False
    order_type = mt5.ORDER_TYPE_BUY if side > 0 else mt5.ORDER_TYPE_SELL
    margin = mt5.order_calc_margin(order_type, symbol, lots.lots, entry)
    if margin is None or margin > acc.margin_free * config.MAX_MARGIN_PCT / 100:
        log.info("%s : signal %s REFUSÉ : marge requise %s > %d %% de la marge libre (%.2f)", LABEL, sf,
                 f"{margin:.2f}" if margin is not None else "?", config.MAX_MARGIN_PCT, acc.margin_free)
        return False
    log.info("%s : SIGNAL %s (mouvement %+.3f %% sur %d min, seuil %.3f %%) entrée≈%.2f stop de sécurité=%.2f lots=%s risque max=%.2f (%.1f %%)",
             LABEL, sf.upper(), m * 100, params.L, thr * 100, entry, sl, lots.lots, lots.risk_money, lots.risk_pct)
    req = {"action": mt5.TRADE_ACTION_DEAL, "symbol": symbol, "volume": lots.lots, "type": order_type,
           "price": entry, "sl": round(sl, info.digits), "tp": 0.0, "deviation": config.DEVIATION,
           "magic": config.MAGIC, "comment": "trendbot dsi", "type_time": mt5.ORDER_TIME_GTC,
           "type_filling": lm.filling_type(symbol)}
    ok = lm.send(req, trade, f"{sf.upper()} {symbol} {lots.lots} lots")
    if ok and trade:
        lm.append_trade_log({"heure_utc": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"), "marche": symbol,
                             "sens": "long" if side > 0 else "short", "lots": lots.lots, "entree": round(entry, info.digits),
                             "stop": round(sl, info.digits), "risque_$": round(lots.risk_money, 2),
                             "risque_%": round(lots.risk_pct, 2), "ligne": "DSI", "touches": 0,
                             "spread_R": round(spread / dist, 3), "capital_simule": round(equity, 2)})
    return ok


def step(symbol: str, lm, trade: bool, beat: dict) -> None:
    t, c = closes(symbol, params.sig_n + params.L + 5)
    tick = mt5.symbol_info_tick(symbol)
    if c is None or tick is None:
        log.warning("%s : pas de bougies 1 minute", LABEL)
        return
    if tick.time - (int(t[-1]) + 60) > 90:           # heure du serveur : on ne décide jamais sur une bougie ancienne
        if time.time() - beat.get("stale", 0) > 900:
            beat["stale"] = time.time()
            log.warning("%s : dernière bougie trop ancienne (marché fermé ou MT5 en retard) : aucune décision", LABEL)
        return
    mine = lm.my_positions(symbol)
    pos = 0 if not mine else (1 if mine[0].type == mt5.POSITION_TYPE_BUY else -1)
    action, m, thr = decide(pos, c, params)
    if action in ("close", "flip_buy", "flip_sell"):
        closed = all([close_position(p, lm, trade, "le mouvement s'est inversé") for p in mine])
        if trade and not closed:
            return
    if action in ("buy", "flip_buy"):
        open_position(symbol, 1, c, m, thr, lm, trade)
    elif action in ("sell", "flip_sell"):
        open_position(symbol, -1, c, m, thr, lm, trade)
    if time.time() - beat.get("t", 0) > 900:           # un point toutes les 15 min, pas une ligne par minute
        beat["t"] = time.time()
        log.info("%s : en veille | mouvement %+.3f %% sur %d min (seuil %.3f %%) | position : %s | gain du jour %+.2f",
                 LABEL, m * 100, params.L, thr * 100, {1: "achat", -1: "vente", 0: "aucune"}[pos], day_pnl(symbol, lm))


def run(lm, trade: bool, once: bool) -> None:
    symbol = config.DSI_SYMBOL
    if mt5.symbol_info(symbol) is None or not mt5.symbol_select(symbol, True):
        raise SystemExit(f"{symbol} : introuvable chez ce broker (cette stratégie ne marche que sur ce marché de Deriv).")
    log.info("Stratégie : suivi de tendance sur %s (mouvement de %d min, seuil %.1f, entrée seulement en phase de tendance, "
             "stop de sécurité %.1fx). Une décision par minute.", symbol, params.L, params.k, params.stop_mult)
    beat: dict = {}
    while True:
        try:
            ti = mt5.terminal_info()
            if ti is None or not ti.connected:
                log.warning("MT5 déconnecté : tentative de reconnexion")
                mt5.shutdown()
                if not mt5.initialize():
                    raise RuntimeError(f"reconnexion MT5 impossible : {mt5.last_error()}")
            step(symbol, lm, trade, beat)
        except Exception:
            if once:
                raise
            log.exception("Erreur pendant le passage : le bot continue à la minute suivante")
        if once:
            return
        time.sleep(60 - (time.time() % 60) + 2)
