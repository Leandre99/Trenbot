"""Réglages du bot. Modifie ici, pas dans le code."""

# Nom affiché -> noms possibles chez le broker (le bot prend le premier qui existe dans ton MT5)
SYMBOLS = {
    "Volatility 10":  ["Volatility 10 Index"],
    "Volatility 25":  ["Volatility 25 Index"],
    "Volatility 50":  ["Volatility 50 Index"],
    "Volatility 75":  ["Volatility 75 Index"],
    "Volatility 100": ["Volatility 100 Index"],
    "Step Index":     ["Step Index"],
    "Or":             ["XAUUSD"],
    # Forex : version « micro » en priorité (lot minimum 10x plus petit, adapté aux petits comptes)
    "EUR/USD":        ["EURUSDmicro", "EURUSD"],
    "GBP/USD":        ["GBPUSDmicro", "GBPUSD"],
    "USD/JPY":        ["USDJPYmicro", "USDJPY"],
    "USD/CAD":        ["USDCADmicro", "USDCAD"],
    "USD/CHF":        ["USDCHFmicro", "USDCHF"],
    "NZD/USD":        ["NZDUSDmicro", "NZDUSD"],
    "AUD/USD":        ["AUDUSDmicro", "AUDUSD"],
    "AUD/JPY":        ["AUDJPY"],
    "EUR/AUD":        ["EURAUD"],
    "EUR/CAD":        ["EURCAD"],
    "EUR/CHF":        ["EURCHF"],
    "EUR/GBP":        ["EURGBP"],
    "EUR/JPY":        ["EURJPY"],
    "GBP/AUD":        ["GBPAUD"],
    "GBP/JPY":        ["GBPJPY"],
    "AUD/CAD":        ["AUDCAD"],
    "AUD/CHF":        ["AUDCHF"],
}

# Marchés analysés. On NE filtre PAS sur les résultats passés : le test a montré que ça n'aide pas.
# Les marchés dont le lot minimum est trop gros pour ton capital sont refusés automatiquement (et signalés au journal).
ACTIVE = list(SYMBOLS)

# Stratégie du bot :
#   "dsi"    = suivi de tendance sur le Drift Switch Index 10 (une décision par minute). C'est la seule stratégie
#              qui gagne après frais dans les tests (69 jours de données : à confirmer en démo).
#   "lignes" = ancienne stratégie (rebond sur lignes de tendance, 24 marchés) : PERDANTE sur 16 ans, gardée pour mémoire.
STRATEGY = "dsi"
DSI_SYMBOL = "Drift Switch Index 10"
DSI_L = 20                # minutes du mouvement suivi
DSI_K = 2.0               # seuil d'entrée (multiples du bruit normal)
DSI_STOP_MULT = 6.0       # stop de sécurité large, jamais touché dans les tests : la sortie normale est l'inversion du mouvement
DSI_MIN_SPREAD_PCT = 0.07 # on n'entre QUE si le spread atteint ce % du prix : Deriv élargit le spread pendant les phases de tendance
                          # (spread serré = phase calme, où suivre le mouvement perd). C'est le signal de phase le plus fiable.
DSI_MAX_SPREAD_PCT = 0.20 # garde-fou : spread anormal, on n'entre pas

CAPITAL_CAP = None        # None = le bot utilise le VRAI capital du compte (option avancée : un nombre = capital fictif + gains/pertes du bot)
RISK_PCT = 1.0            # % du capital risqué par trade (100 $ -> 1 $)
MAX_RISK_PCT = 3.0        # si le lot minimum dépasse ce %, le trade est refusé
MAX_POSITIONS = 3         # positions ouvertes en même temps (risque total max ~ 3 %). La simulation montrait des baisses un peu plus faibles avec 2 ; 5 est nettement pire
DAILY_LOSS_STOP_PCT = 3.0 # plus de nouveaux trades du jour si le capital baisse de ce % depuis le matin
MAX_SPREAD_R = 0.15       # refus si le spread dépasse ce multiple du risque (distance au stop) : le coût mange le trade
MAX_MARGIN_PCT = 50      # un trade ne peut pas immobiliser plus de ce % de la marge libre (évite le stop-out)
MAX_SIGNAL_AGE_S = 900    # on n'ouvre un trade que dans les 15 min qui suivent la clôture (24 marchés ≈ 5 min d'analyse)

MAGIC = 20260501         # identifiant des ordres du bot (pour ne toucher qu'à ses positions)
DEVIATION = 20            # glissement max accepté, en points

# ---- Réglages modifiés depuis l'interface (settings.json) : priment sur les valeurs ci-dessus ----
import json as _json
from pathlib import Path as _Path

EDITABLE = ("CAPITAL_CAP", "RISK_PCT", "MAX_RISK_PCT", "MAX_POSITIONS", "DAILY_LOSS_STOP_PCT", "MAX_SPREAD_R")
_f = _Path(__file__).with_name("settings.json")
if _f.exists():
    try:
        for _k, _v in _json.loads(_f.read_text(encoding="utf-8")).items():
            if _k in EDITABLE:
                globals()[_k] = _v
    except Exception:  # fichier abîmé : on garde les valeurs par défaut
        pass
