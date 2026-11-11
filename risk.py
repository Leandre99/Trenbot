"""Calcul de la taille de position (lots) à partir du risque accepté.

Idée : on décide combien on accepte de perdre si le stop est touché (par ex. 1 % du capital),
puis on en déduit les lots. Si même le lot minimum du broker dépasse le risque maximal autorisé,
le trade est refusé (c'est fréquent avec un petit capital sur l'or ou le forex).
"""
import math
from dataclasses import dataclass


def spread_cost_r(spread: float, entry: float, sl: float) -> float:
    """Coût du spread exprimé en R (1 R = distance entrée -> stop)."""
    dist = abs(entry - sl)
    return float("inf") if dist <= 0 else spread / dist


def daily_halt(equity: float, start_equity: float, loss_pct: float) -> bool:
    """True si le capital a baissé de `loss_pct` % (ou plus) depuis le début de la journée, ou s'il est épuisé."""
    return equity <= 0 or equity < start_equity * (1 - loss_pct / 100)


def bot_day_halt(day_pnl: float, start_equity: float, loss_pct: float) -> bool:
    """True si le BOT a perdu `loss_pct` % (ou plus) du capital de départ de la journée. `day_pnl` = gain/perte du bot aujourd'hui."""
    return start_equity <= 0 or day_pnl <= -start_equity * loss_pct / 100


@dataclass
class LotResult:
    lots: float
    risk_money: float       # perte réelle en argent si le stop est touché
    risk_pct: float
    reason: str = ""        # non vide = trade refusé


def lot_for_risk(equity: float, risk_pct: float, max_risk_pct: float, entry: float, sl: float,
                 tick_size: float, tick_value: float, vol_min: float, vol_max: float, vol_step: float) -> LotResult:
    dist = abs(entry - sl)
    if dist <= 0 or tick_size <= 0 or tick_value <= 0:
        return LotResult(0.0, 0.0, 0.0, "distance de stop ou specs du symbole invalides")

    loss_per_lot = dist / tick_size * tick_value          # perte si 1 lot touche le stop
    target = equity * risk_pct / 100
    lots = math.floor(target / loss_per_lot / vol_step + 1e-9) * vol_step

    if lots < vol_min:
        min_risk = vol_min * loss_per_lot
        if min_risk > equity * max_risk_pct / 100:
            return LotResult(0.0, min_risk, min_risk / equity * 100,
                             f"lot minimum {vol_min} risquerait {min_risk:.2f} "
                             f"({min_risk / equity * 100:.1f} % > {max_risk_pct} % max)")
        lots = vol_min

    lots = min(lots, vol_max)
    decimals = max(0, -int(math.floor(math.log10(vol_step)))) if vol_step < 1 else 0
    lots = round(lots, decimals)
    risk_money = lots * loss_per_lot
    return LotResult(lots, risk_money, risk_money / equity * 100)


def min_lot_stop(equity: float, max_risk_pct: float, dist: float, floor: float, loss_per_min_lot_per_price: float):
    """Petit capital : on trade le lot MINIMUM et on rapproche le stop pour que la perte au stop tienne dans la limite.
    dist = distance de stop prévue (prix) ; floor = distance la plus courte acceptée (plancher testé / minimum du broker) ;
    loss_per_min_lot_per_price = perte du lot minimum pour 1 unité de prix.
    Retourne (distance retenue, perte au stop, % du capital). Si même le plancher dépasse la limite, on garde le plancher."""
    cap = equity * max_risk_pct / 100 / loss_per_min_lot_per_price
    d = min(dist, max(cap, floor))
    risk = d * loss_per_min_lot_per_price
    return d, risk, risk / equity * 100
