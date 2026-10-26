# trendbot

Bot MT5 basé sur la stratégie « rebond sur ligne de tendance » avec analyse descendante
(lignes tracées en semaine / jour / 4h, entrée en H1, stop derrière la ligne, stop suiveur sur les pivots).

> **Démo uniquement pour l'instant.** Le backtest (1 an, Deriv) est mitigé : voir « Limites » plus bas.

## Installation (Windows)

```
pip install -r requirements.txt
```

1. Ouvre **MetaTrader 5** et connecte-toi à ton compte **démo** (le bot ne gère jamais ton mot de passe).
2. Dans MT5 : *Outils > Options > Expert Advisors* : coche « Autoriser le trading algorithmique ».

## Utilisation

```
python live_mt5.py            # essai à blanc : analyse et affiche, aucun ordre
python live_mt5.py --trade    # envoie des ordres (refusé si le compte n'est pas une démo)
python live_mt5.py --once     # un seul passage
```

Le bot se réveille 5 s après la clôture de chaque bougie H1. Laisse le PC et MT5 allumés.

## Gestion du risque et des lots (`config.py`, `risk.py`)

- Risque par trade : **1 %** du capital (100 $ -> 1 $), calculé à partir de la distance du stop.
- Lots : `risque en $ / perte par lot au stop`, arrondi **vers le bas** au pas du broker.
- Si même le **lot minimum** risque plus de **3 %**, le trade est refusé (fréquent sur l'or / forex avec 100 $).
- **3 positions max** en même temps, **une seule par marché**.
- **Arrêt du jour** si le capital baisse de 3 % depuis le matin.
- Pas d'entrée si le signal a plus de 10 min (bot redémarré en retard, etc.).
- Chaque ordre a un stop-loss dès l'ouverture, pas de take-profit : on sort au stop suiveur.

## Fichiers

| Fichier | Rôle |
|---|---|
| `live_mt5.py` | le bot (MT5) |
| `mtf.py` | stratégie : lignes multi-échelles, signal, stop suiveur, backtest |
| `strategy.py` | pivots, lignes de tendance, statistiques |
| `risk.py` | calcul des lots |
| `config.py` | réglages |
| `data.py`, `run_mtf.py`, `plot_example.py` | données Deriv, backtest, graphique d'exemple |
| `test_risk.py` | tests du calcul de lots |

## Limites

- Backtest sur 1 an seulement ; coûts réels (spread, commissions) à mesurer en démo.
- La sélection des marchés actifs (`ACTIVE`) a été faite d'après ce même backtest : biais possible.
- Les bougies jour/semaine de MT5 suivent l'heure du serveur du broker, légèrement différente des données du backtest.
- L'échelle mensuelle de la vidéo n'est pas implémentée.
