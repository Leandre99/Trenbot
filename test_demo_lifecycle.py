"""Test RÉEL sur compte DÉMO uniquement : ouvre 1 position au lot minimum avec stop-loss, déplace le stop, la ferme.
Utilise un identifiant (magic) à part : aucune de tes autres positions n'est touchée.
Refuse de tourner si le compte n'est pas une démo. La position de test est TOUJOURS refermée à la fin.

Usage : python test_demo_lifecycle.py [symbole]     (défaut : Volatility 75 Index, ouvert 24h/24)
"""
import sys
import time
from datetime import datetime, timedelta, timezone

import MetaTrader5 as mt5

import config
import live_mt5 as bot

TEST_MAGIC = 99887766
SYMBOL = sys.argv[1] if len(sys.argv) > 1 else "Volatility 75 Index"


def step(ok: bool, msg: str) -> None:
    print(("OK    " if ok else "ÉCHEC ") + msg, flush=True)
    if not ok:
        raise SystemExit(f"Test arrêté : {msg}")


def my_test_positions():
    return [p for p in (mt5.positions_get(symbol=SYMBOL) or []) if p.magic == TEST_MAGIC]


def close_all() -> None:
    for p in my_test_positions():
        tick = mt5.symbol_info_tick(p.symbol)
        buy = p.type == mt5.POSITION_TYPE_BUY
        req = {"action": mt5.TRADE_ACTION_DEAL, "symbol": p.symbol, "volume": p.volume,
               "type": mt5.ORDER_TYPE_SELL if buy else mt5.ORDER_TYPE_BUY, "position": p.ticket,
               "price": tick.bid if buy else tick.ask, "deviation": config.DEVIATION, "magic": TEST_MAGIC,
               "comment": "test fermeture", "type_time": mt5.ORDER_TIME_GTC, "type_filling": bot.filling_type(p.symbol)}
        res = mt5.order_send(req)
        print("fermeture :", getattr(res, "retcode", None), getattr(res, "comment", ""), flush=True)


if not mt5.initialize():
    raise SystemExit(f"MT5 injoignable : {mt5.last_error()}")
config.MAGIC = TEST_MAGIC            # le bot ne voit QUE la position de test
try:
    acc = mt5.account_info()
    step(acc.trade_mode == mt5.ACCOUNT_TRADE_MODE_DEMO, f"compte démo confirmé ({acc.login}, {acc.server})")
    mt5.symbol_select(SYMBOL, True)
    info, tick = mt5.symbol_info(SYMBOL), mt5.symbol_info_tick(SYMBOL)
    step(info is not None and tick is not None and tick.ask > 0, f"{SYMBOL} : prix reçu (ask={tick.ask}, bid={tick.bid})")
    step(len(my_test_positions()) == 0, "aucune position de test déjà ouverte")

    min_dist = max(info.trade_stops_level * info.point, 100 * info.point)
    entry = tick.ask
    sl = round(entry - 3 * min_dist, info.digits)
    req = {"action": mt5.TRADE_ACTION_DEAL, "symbol": SYMBOL, "volume": info.volume_min, "type": mt5.ORDER_TYPE_BUY,
           "price": entry, "sl": sl, "tp": 0.0, "deviation": config.DEVIATION, "magic": TEST_MAGIC,
           "comment": "test trendbot", "type_time": mt5.ORDER_TIME_GTC, "type_filling": bot.filling_type(SYMBOL)}

    step(bot.check_order(req, "achat test"), "order_check accepte l'ordre (volume, stop, marge, exécution)")
    step(bot.send(req, True, f"ACHAT TEST {SYMBOL} {info.volume_min} lot"), "ordre envoyé et exécuté")
    time.sleep(1)
    pos = my_test_positions()
    step(len(pos) == 1, "la position apparaît bien chez le broker")
    p = pos[0]
    step(abs(p.sl - sl) < info.point * 2, f"le stop-loss est bien posé dès l'ouverture (sl={p.sl})")
    step(len(bot.my_positions(SYMBOL)) == 1, "le bot reconnaît sa position (identifiant magic)")

    # déplacement du stop (même requête que le stop suiveur du bot)
    new_sl = round(p.sl + min_dist, info.digits)
    tick = mt5.symbol_info_tick(SYMBOL)
    step(new_sl < tick.bid - min_dist, "le nouveau stop respecte la distance minimale")
    mod = {"action": mt5.TRADE_ACTION_SLTP, "position": p.ticket, "symbol": SYMBOL, "sl": new_sl, "tp": p.tp}
    step(bot.send(mod, True, f"SL suiveur {p.sl} -> {new_sl}"), "modification du stop acceptée")
    time.sleep(1)
    p2 = my_test_positions()[0]
    step(abs(p2.sl - new_sl) < info.point * 2, f"le stop a bien été déplacé (sl={p2.sl})")

    # le P&L du bot (utilisé pour le capital simulé) voit la position
    pnl = bot.bot_pnl(time.time() - 3600)
    print(f"      P&L du bot vu par bot_pnl : {pnl:+.2f} $ (spread payé à l'ouverture)", flush=True)
finally:
    close_all()
    time.sleep(1)
    left = my_test_positions()
    if left:
        print("ÉCHEC : position de test encore ouverte ! Ferme-la à la main dans MT5 (commentaire « test trendbot »).")
    else:
        print("OK    position de test fermée")
        now = datetime.now(timezone.utc)
        deals = [d for d in (mt5.history_deals_get(now - timedelta(hours=3), now + timedelta(days=1)) or [])
                 if d.magic == TEST_MAGIC]
        print(f"      historique : {len(deals)} deals du test, résultat final "
              f"{sum(d.profit + d.commission + d.swap for d in deals):+.2f} $")
    mt5.shutdown()
