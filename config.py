"""Réglages du bot. Modifie ici, pas dans le code."""

# Nom affiché -> noms possibles chez le broker (le bot prend le premier qui existe dans ton MT5)
SYMBOLS = {
    "Volatility 10":  ["Volatility 10 Index"],
    "Volatility 25":  ["Volatility 25 Index"],
    "Volatility 50":  ["Volatility 50 Index"],
    "Volatility 75":  ["Volatility 75 Index"],
    "Volatility 100": ["Volatility 100 Index"],
    "Step Index":     ["Step Index"],
    "EUR/USD":        ["EURUSD"],
    "GBP/USD":        ["GBPUSD"],
    "USD/JPY":        ["USDJPY"],
    "Or":             ["XAUUSD"],
}

# Marchés réellement tradés (retire-en pour limiter). Par défaut ceux qui étaient positifs au backtest.
ACTIVE = ["Volatility 25", "Volatility 75", "Step Index", "USD/JPY", "Or", "GBP/USD"]

RISK_PCT = 1.0            # % du capital risqué par trade (100 $ -> 1 $)
MAX_RISK_PCT = 3.0        # si le lot minimum dépasse ce %, le trade est refusé
MAX_POSITIONS = 3         # positions ouvertes en même temps (risque total max ~ 3 %)
DAILY_LOSS_STOP_PCT = 3.0 # plus de nouveaux trades du jour si le capital baisse de ce % depuis le matin
MAX_SIGNAL_AGE_S = 600    # on n'ouvre un trade que dans les 10 min qui suivent la clôture de la bougie

MAGIC = 20260501          # identifiant des ordres du bot (pour ne toucher qu'à ses positions)
DEVIATION = 20            # glissement max accepté, en points
