"""Calcul de la taille de position (lots) à partir du risque accepté.

Idée : on décide combien on accepte de perdre si le stop est touché (par ex. 1 % du capital),
puis on en déduit les lots. Si même le lot minimum du broker dépasse le risque maximal autorisé,
le trade est refusé (c'est fréquent avec un petit capital sur l'or ou le forex).
"""
import math
from dataclasses import dataclass


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
