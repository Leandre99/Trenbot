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

CAPITAL_CAP = 100.0       # le bot calcule lots/marge comme si le compte valait AU PLUS ce montant (None = capital réel)
RISK_PCT = 1.0            # % du capital risqué par trade (100 $ -> 1 $)
MAX_RISK_PCT = 3.0        # si le lot minimum dépasse ce %, le trade est refusé
MAX_POSITIONS = 2         # positions ouvertes en même temps (risque total max ~ 2 %). 2 réduit les baisses vs 3 (simulation), 5 est pire
DAILY_LOSS_STOP_PCT = 3.0 # plus de nouveaux trades du jour si le capital baisse de ce % depuis le matin
MAX_SPREAD_R = 0.15       # refus si le spread dépasse ce multiple du risque (distance au stop) : le coût mange le trade
MAX_MARGIN_PCT = 50      # un trade ne peut pas immobiliser plus de ce % de la marge libre (évite le stop-out)
MAX_SIGNAL_AGE_S = 900    # on n'ouvre un trade que dans les 15 min qui suivent la clôture (24 marchés ≈ 5 min d'analyse)

MAGIC = 20260501          # identifiant des ordres du bot (pour ne toucher qu'à ses positions)
DEVIATION = 20            # glissement max accepté, en points
