"""Bot MT5 : stratégie de rebond sur lignes de tendance multi-échelles (voir mtf.py).

Utilisation (MT5 doit être ouvert et connecté à ton compte) :
    python live_mt5.py              # essai à blanc : analyse et affiche, n'envoie AUCUN ordre
    python live_mt5.py --trade      # envoie de vrais ordres (refusé si le compte n'est pas une démo)
    python live_mt5.py --once       # un seul passage puis arrêt
Le bot ne gère jamais ton mot de passe : il se branche sur le MT5 déjà connecté.
"""
import argparse
import json
import logging
import time
from datetime import datetime, timezone
from pathlib import Path

import MetaTrader5 as mt5
import numpy as np
import pandas as pd

import config
from mtf import GRAN_S, MTFParams, detect_signal, htf_lines, trail_stop
from risk import lot_for_risk
from strategy import atr, find_pivots

HERE = Path(__file__).parent
STATE_FILE = HERE / "state.json"
mp = MTFParams()
log = logging.getLogger("bot")

TF = {"H1": mt5.TIMEFRAME_H1, "H4": mt5.TIMEFRAME_H4, "D1": mt5.TIMEFRAME_D1, "W1": mt5.TIMEFRAME_W1}
BARS = {"H1": 400, "H4": 600, "D1": 500, "W1": 200}


# ---------------------------------------------------------------- utilitaires
def load_state() -> dict:
    try:
        return json.loads(STATE_FILE.read_text())
    except Exception:
        return {}


def save_state(st: dict) -> None:
    STATE_FILE.write_text(json.dumps(st, indent=1))


def resolve_symbols() -> dict:
    available = {s.name.lower(): s.name for s in (mt5.symbols_get() or [])}
    out = {}
    for label in config.ACTIVE:
        for cand in config.SYMBOLS[label]:
            if cand.lower() in available:
                real = available[cand.lower()]
                mt5.symbol_select(real, True)
                out[label] = real
                break
        else:
            log.warning("%s : symbole introuvable chez ce broker (%s), ignoré", label, config.SYMBOLS[label])
    return out


def rates(symbol: str, tf: str) -> pd.DataFrame | None:
    """Bougies CLÔTURÉES uniquement (position 1 = on saute la bougie en cours)."""
    for _ in range(4):  # MT5 télécharge l'historique à la première demande : on réessaie un peu
        r = mt5.copy_rates_from_pos(symbol, TF[tf], 1, BARS[tf])
        if r is not None and len(r) >= 60:
            break
        time.sleep(2)
    else:
        return None
    df = pd.DataFrame(r)
    df.index = pd.to_datetime(df["time"], unit="s")
    return df[["open", "high", "low", "close"]].astype(float)


def my_positions(symbol: str | None = None):
    pos = mt5.positions_get(symbol=symbol) if symbol else mt5.positions_get()
    return [p for p in (pos or []) if p.magic == config.MAGIC]


def filling_type(symbol: str) -> int:
    fm = mt5.symbol_info(symbol).filling_mode
    if fm & 1:
        return mt5.ORDER_FILLING_FOK
    if fm & 2:
        return mt5.ORDER_FILLING_IOC
    return mt5.ORDER_FILLING_RETURN


def send(request: dict, trade: bool, what: str) -> bool:
    if not trade:
        log.info("[ESSAI À BLANC] %s | %s", what, request)
        return True
    res = mt5.order_send(request)
    if res is None or res.retcode != mt5.TRADE_RETCODE_DONE:
        log.error("ORDRE REFUSÉ %s | code=%s %s", what, getattr(res, "retcode", None), getattr(res, "comment", mt5.last_error()))
        return False
    log.info("ORDRE OK %s | ticket=%s prix=%s", what, res.order, res.price)
    return True


# ---------------------------------------------------------------- logique par symbole
def manage_position(pos, h1: pd.DataFrame, trade: bool) -> None:
    """Stop suiveur : remonte (ou descend) le SL derrière le dernier pivot, jamais en arrière."""
    side = "long" if pos.type == mt5.POSITION_TYPE_BUY else "short"
    o, h, l, c = (h1[k].to_numpy() for k in ("open", "high", "low", "close"))
    a = atr(h1, mp.atr_n)[-1]
    is_low, is_high = find_pivots(h1, mp.pivot_n)
    low_idx, high_idx = np.flatnonzero(is_low), np.flatnonzero(is_high)
    t_open = pd.Timestamp(pos.time, unit="s")
    entry_i = int(h1.index.searchsorted(t_open))
    j = len(h1) - 1
    new_sl = trail_stop(side, pos.sl, h, l, low_idx, high_idx, entry_i, j, a, mp)
    info = mt5.symbol_info(pos.symbol)
    tick = mt5.symbol_info_tick(pos.symbol)
    # le stop doit rester à distance minimale du prix
    min_dist = info.trade_stops_level * info.point
    if side == "long":
        if new_sl > pos.sl + info.point and new_sl < tick.bid - min_dist:
            send({"action": mt5.TRADE_ACTION_SLTP, "position": pos.ticket, "symbol": pos.symbol,
                  "sl": round(new_sl, info.digits), "tp": pos.tp},
                 trade, f"SL suiveur {pos.symbol} {pos.sl} -> {new_sl:.5f}")
    else:
        if new_sl < pos.sl - info.point and new_sl > tick.ask + min_dist:
            send({"action": mt5.TRADE_ACTION_SLTP, "position": pos.ticket, "symbol": pos.symbol,
                  "sl": round(new_sl, info.digits), "tp": pos.tp},
                 trade, f"SL suiveur {pos.symbol} {pos.sl} -> {new_sl:.5f}")


def compute_htf(symbol: str):
    """Lignes de tendance W1/D1/H4 du symbole. Retourne None s'il manque de l'historique."""
    htf = {}
    for name in mp.htfs:
        df = rates(symbol, name)
        if df is None:
            return None
        htf[name] = htf_lines(df, 0, mp, only_last=True)
    return htf


def export_rows(symbol: str, htf: dict) -> list[str]:
    """Lignes de dessin pour l'indicateur MQL5 : symbole,échelle,sens,touches,n°,heure,prix.
    La ligne est découpée en segments tous les ~10 bougies pour suivre les trous (week-ends)."""
    rows = []
    for name, (opens, lns) in htf.items():
        g = GRAN_S[name]
        k = len(opens) - 1
        for side, ln in zip(("up", "down"), lns[k]):
            if ln is None:
                continue
            slope, inter, touches = ln
            idxs = list(range(max(0, k - 80), k + 1, 10))
            if idxs[-1] != k:
                idxs.append(k)
            idxs.append(k + 15)
            for seq, idx in enumerate(idxs):
                t = int(opens[idx]) if idx <= k else int(opens[k] + (idx - k) * g)
                rows.append(f"{symbol},{name},{side},{touches},{seq},{t},{slope * idx + inter:.6f}")
    return rows


def write_lines_file(rows: list[str]) -> None:
    path = Path(mt5.terminal_info().commondata_path) / "Files" / "trendbot_lines.csv"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(rows) + "\n", encoding="ascii")


def look_for_entry(label: str, symbol: str, h1: pd.DataFrame, equity: float, trade: bool, htf: dict | None) -> bool | None:
    """True = ordre envoyé, False = bougie examinée sans entrée, None = bougie NON examinée (à retenter)."""
    tk = mt5.symbol_info_tick(symbol)
    if tk is None:
        return None
    # heure du SERVEUR (les bougies MT5 sont en heure serveur, pas en heure du PC)
    age = tk.time - (h1.index[-1].timestamp() + 3600)
    if age > config.MAX_SIGNAL_AGE_S:
        if not getattr(look_for_entry, "age_warned", False):
            look_for_entry.age_warned = True
            log.info("Dernière bougie H1 fermée il y a %d min (> %d min) : aucune NOUVELLE entrée possible dans ce passage. "
                     "Laisse le bot tourner (il agit à chaque heure pile) ou teste avec --ignore-age en essai à blanc.",
                     age // 60, config.MAX_SIGNAL_AGE_S // 60)
        return None  # bougie trop ancienne : on n'entre pas en retard (None = pas examinée)

    if htf is None:
        log.warning("%s : pas assez d'historique W1/D1/H4", label)
        return None

    o, h, l, c = (h1[k].to_numpy() for k in ("open", "high", "low", "close"))
    t = h1.index.values.astype("datetime64[s]").astype("int64")
    i = len(h1) - 1
    a = atr(h1, mp.atr_n)[i]
    if np.isnan(a) or a <= 0:
        return False
    sig = detect_signal(o, h, l, c, t, i, a, htf, mp)
    if sig is None:
        return False

    side, lv, name, touches = sig[:4]
    info = mt5.symbol_info(symbol)
    tick = mt5.symbol_info_tick(symbol)
    sgn = 1 if side == "long" else -1
    entry = tick.ask if side == "long" else tick.bid
    sl = sig[4] if len(sig) > 4 else lv - sgn * mp.sl_atr * a   # mode "reclaim" : stop sous le creux du test
    if (entry - sl) * sgn <= info.trade_stops_level * info.point:
        log.info("%s : signal %s ignoré (stop trop proche du prix)", label, side)
        return False

    # le spread est un coût payé d'entrée : s'il représente une grosse part de la distance au stop, le trade est perdant d'avance
    spread = tick.ask - tick.bid
    cost_r = spread / abs(entry - sl)
    if cost_r > config.MAX_SPREAD_R:
        log.info("%s : signal %s REFUSÉ : spread %.5f = %.2f R de la distance au stop (max %.2f R)",
                 label, side, spread, cost_r, config.MAX_SPREAD_R)
        return False

    tv = info.trade_tick_value_loss if info.trade_tick_value_loss > 0 else info.trade_tick_value
    lots = lot_for_risk(equity, config.RISK_PCT, config.MAX_RISK_PCT, entry, sl,
                        info.trade_tick_size, tv, info.volume_min, info.volume_max, info.volume_step)
    if lots.reason:
        log.info("%s : signal %s (ligne %s) REFUSÉ : %s", label, side, name, lots.reason)
        return False

    order_type = mt5.ORDER_TYPE_BUY if side == "long" else mt5.ORDER_TYPE_SELL
    margin = mt5.order_calc_margin(order_type, symbol, lots.lots, entry)
    free = mt5.account_info().margin_free
    if config.CAPITAL_CAP:
        free = min(free, config.CAPITAL_CAP)
    if margin is None or margin > free * config.MAX_MARGIN_PCT / 100:
        log.info("%s : signal %s REFUSÉ : marge requise %s > %d %% de la marge libre (%.2f)",
                 label, side, f"{margin:.2f}" if margin is not None else "?", config.MAX_MARGIN_PCT, free)
        return False

    log.info("%s : SIGNAL %s sur ligne %s (%d touches) entrée≈%.5f stop=%.5f lots=%s risque=%.2f (%.1f %%)",
             label, side.upper(), name, touches, entry, sl, lots.lots, lots.risk_money, lots.risk_pct)
    req = {"action": mt5.TRADE_ACTION_DEAL, "symbol": symbol, "volume": lots.lots,
           "type": mt5.ORDER_TYPE_BUY if side == "long" else mt5.ORDER_TYPE_SELL,
           "price": entry, "sl": round(sl, info.digits), "tp": 0.0,
           "deviation": config.DEVIATION, "magic": config.MAGIC,
           "comment": f"trendbot {name}", "type_time": mt5.ORDER_TIME_GTC,
           "type_filling": filling_type(symbol)}
    return send(req, trade, f"{side.upper()} {symbol} {lots.lots} lots")


# ---------------------------------------------------------------- un passage complet
def cycle(symbols: dict, trade: bool, lines_only: bool = False) -> None:
    acc = mt5.account_info()
    equity = min(acc.equity, config.CAPITAL_CAP) if config.CAPITAL_CAP else acc.equity
    st = load_state()
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    if st.get("day") != today:
        st = {"day": today, "start_equity": equity, "done": {}}
    done = st.setdefault("done", {})
    halted = equity < st["start_equity"] * (1 - config.DAILY_LOSS_STOP_PCT / 100)
    if halted:
        log.warning("Limite de perte du jour atteinte (%.2f -> %.2f) : plus de nouveaux trades aujourd'hui",
                    st["start_equity"], equity)

    log.info("--- passage | capital=%.2f | positions du bot=%d/%d", equity, len(my_positions()), config.MAX_POSITIONS)
    line_rows = []
    look_for_entry.age_warned = False
    for label, symbol in symbols.items():
        h1 = rates(symbol, "H1")
        if h1 is None:
            log.warning("%s : pas de données H1", label)
            continue
        htf = compute_htf(symbol)
        if htf is not None:
            line_rows += export_rows(symbol, htf)
        if lines_only:
            continue
        pos = my_positions(symbol)
        if pos:
            manage_position(pos[0], h1, trade)
            continue
        key = f"{symbol}:{h1.index[-1]}"
        if done.get(symbol) == key:
            continue  # cette bougie a déjà été examinée
        if halted or len(my_positions()) >= config.MAX_POSITIONS:
            continue
        if look_for_entry(label, symbol, h1, equity, trade, htf) is not None:
            done[symbol] = key   # marquée « examinée » seulement si elle l'a vraiment été
    write_lines_file(line_rows)
    log.info("lignes de tendance exportées pour l'indicateur MT5 (%d points)", len(line_rows))
    if trade and not lines_only:   # l'essai à blanc n'enregistre rien : on peut le relancer à volonté
        save_state(st)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--trade", action="store_true", help="envoyer de vrais ordres (sinon essai à blanc)")
    ap.add_argument("--once", action="store_true", help="un seul passage")
    ap.add_argument("--lines-only", action="store_true", help="exporter seulement les lignes pour l'indicateur (aucun trade)")
    ap.add_argument("--ignore-age", action="store_true",
                    help="essai à blanc seulement : analyse la dernière bougie même si elle est ancienne")
    ap.add_argument("--allow-real", action="store_true", help="autoriser un compte RÉEL (déconseillé)")
    args = ap.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s",
                        handlers=[logging.StreamHandler(), logging.FileHandler(HERE / "bot.log", encoding="utf-8")])
    if args.ignore_age:
        if args.trade:
            raise SystemExit("--ignore-age est interdit avec --trade (il entrerait sur des signaux périmés).")
        config.MAX_SIGNAL_AGE_S = 10 ** 9
    if not mt5.initialize():
        raise SystemExit(f"Impossible de se connecter à MT5 (ouvre-le et connecte-toi) : {mt5.last_error()}")
    acc = mt5.account_info()
    is_demo = acc.trade_mode == mt5.ACCOUNT_TRADE_MODE_DEMO
    log.info("Compte %s | %s | %s | solde=%.2f %s", acc.login, acc.server, "DÉMO" if is_demo else "RÉEL", acc.balance, acc.currency)
    if args.trade and not is_demo and not args.allow_real:
        raise SystemExit("Compte RÉEL détecté : refus de trader. (Option --allow-real si tu assumes, mais teste d'abord en démo.)")
    if not args.trade:
        log.info("MODE ESSAI À BLANC : aucun ordre ne sera envoyé (utilise --trade pour trader sur la démo)")

    symbols = resolve_symbols()
    log.info("Marchés suivis : %s", ", ".join(f"{k}={v}" for k, v in symbols.items()))
    try:
        while True:
            cycle(symbols, args.trade and not args.lines_only, args.lines_only)
            if args.once:
                break
            # prochain passage : 5 s après la clôture de la prochaine bougie H1
            wait = 3600 - (time.time() % 3600) + 5
            log.info("prochain passage dans %d min", wait // 60)
            time.sleep(wait)
    finally:
        mt5.shutdown()


if __name__ == "__main__":
    main()
