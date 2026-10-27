# trendbot

Bot MT5 : rebond sur lignes de tendance avec analyse descendante.
Lignes tracées en **semaine / jour / 4h**, entrée à la clôture de chaque bougie **H1**, achats et ventes,
stop-loss dès l'ouverture, puis stop suiveur derrière les pivots. Pas de take-profit : on sort au stop.

> **Compte démo uniquement.** Le bot refuse de trader sur un compte réel. Le backtest (1 an) est positif mais
> inégal selon les marchés et les périodes : le vrai test, ce sont quelques semaines en démo (voir `report.py`).

## Installation (Windows)

```
pip install -r requirements.txt
```

1. Ouvre **MetaTrader 5**, connecte-toi à ton compte **démo** (le bot ne gère jamais ton mot de passe).
2. *Outils > Options > Expert Advisors* : coche « Autoriser le trading algorithmique ».

## Utilisation

```
python live_mt5.py                 # essai à blanc en continu : analyse, valide chaque ordre auprès de MT5, n'envoie RIEN
python live_mt5.py --trade         # trade sur la démo, en continu (se réveille à chaque heure pile)
python live_mt5.py --once          # un seul passage
python live_mt5.py --once --ignore-age   # essai à blanc : analyse la dernière bougie même si elle est ancienne
python live_mt5.py --lines-only    # exporte seulement les lignes pour l'indicateur (aucun trade)
```

Laisse le PC et MT5 allumés. Un passage dure 1 à 3 minutes (24 marchés). Arrêt : `Ctrl + C` (les positions
ouvertes gardent leur stop-loss chez le broker). Si une erreur survient pendant un passage, le bot le note dans
`bot.log` et continue à l'heure suivante ; si MT5 se déconnecte, il tente de se reconnecter.

Bilan à tout moment : `python report.py 30` (trades fermés, gain net, taux de réussite, par marché).
Chaque ordre ouvert est aussi noté dans `trades_log.csv`.

## Gestion du risque et des lots (`config.py`, `risk.py`)

- Lots = `risque visé en $ / perte par lot au stop`, arrondi vers le bas au pas du broker. Dépend donc du marché.
- Risque visé : **1 %** du capital par trade. Si même le lot minimum dépasse **3 %**, le trade est refusé.
- `CAPITAL_CAP = 100` : le bot raisonne comme si le compte valait 100 $ **+ ses propres gains/pertes** (mets `None` pour utiliser le capital réel).
- **2 positions max**, une seule par marché (`MAX_POSITIONS`). **Arrêt du jour** si le capital baisse de 3 %.
- **Filtre de spread** : refus si le spread dépasse 0,15 R (15 % de la distance au stop).
- **Garde-fou de marge** : un trade ne peut pas immobiliser plus de 50 % de la marge libre.
- Pas d'entrée si la bougie a plus de 15 min (redémarrage tardif).
- Chaque ordre est validé par `order_check` avant envoi.

## Voir les lignes sur les graphiques MT5

```
python install_indicator.py        # copie et compile l'indicateur dans MT5 (une fois)
python live_mt5.py --lines-only    # exporte les lignes
```

MT5 : *Navigateur > Indicateurs > TrendBot > TrendBotLines*, glisse-le sur un graphique.
Vert = haussière, rouge = baissière ; semaine épais, jour moyen, 4h fin.

## Tests

```
python test_risk.py                # lots
python test_bot.py                 # lignes, signaux, stop suiveur, spread, perte du jour, export (données fabriquées)
python test_demo_lifecycle.py      # RÉEL sur démo uniquement : ouvre 1 lot min avec stop, déplace le stop, ferme
```

## Outils d'analyse

| Fichier | Rôle |
|---|---|
| `show_specs.py`, `list_markets.py` | caractéristiques des marchés chez ton broker |
| `show_risk.py 100` | lots et risque en $ par marché pour un capital donné |
| `run_mtf.py`, `scan_spread.py`, `tf_test.py`, `compare_entries.py`, `split_check.py`, `step_m15_test.py` | backtests et comparaisons |

## Ce que les tests ont montré

- H1 tient avec les vrais spreads (≈ +77 R sur 24 marchés en 1 an avec le filtre) ; M15 perd en moyenne (sauf Step Index, mis de côté).
- L'entrée en deux temps (retour après cassure) est moins bonne que le rebond direct (`entry_mode="reclaim"` reste disponible).
- Garder seulement les marchés positifs ne marche pas : on garde les 24, le filtre de spread écarte les mauvais coûts.

## Ce qu'on peut attendre avec 100 $ (simulation avec les vraies règles : `python simulate_account.py`)

- Sur l'année passée : +19 % mais **pire baisse −72 %** (3 positions, 100 $). Sur 3 mois : médiane ≈ 0 %, pire 10 % ≈ −45 %,
  meilleur 10 % ≈ +74 %, seulement ~49 % des périodes gagnantes. À 100 $, le bot ne prend qu'environ 1 signal sur 5
  (positions déjà prises, lot minimum trop gros, arrêt du jour, spread).
- **2 positions max** donne une baisse moyenne plus faible que 3 dans les 6 combinaisons testées (`python sweep_risk.py`) ; 5 est nettement pire.
- Les autres écarts entre réglages (risque 0,5/1/2 %, capital 100/250/500/1000 $) sont du bruit : ne pas optimiser dessus.
- C'est un **test**, pas une source de revenu : lancer en démo 2 à 3 mois sans toucher aux réglages, puis comparer avec `python report.py`.

## Limites

- Backtest sur 1 an : la 1re moitié était proche de zéro, la 2e très positive. Aucun avantage stable n'est prouvé.
- Avec 100 $, beaucoup de marchés sont refusés (lot minimum trop gros) : Volatility 10/25/50/100, Step Index, l'or.
- Les bougies jour/semaine de MT5 suivent l'heure du serveur du broker, légèrement différente des données du backtest.
- L'échelle mensuelle de la vidéo n'est pas implémentée.
