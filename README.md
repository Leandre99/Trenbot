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

## Tableau de bord (le plus simple)

Double-clic sur **`lancer_interface.bat`** (ou `python dashboard.py`) : une page s'ouvre dans ton navigateur
(`http://127.0.0.1:8765`, uniquement sur ton PC). **Garde la fenêtre noire ouverte** tant que tu l'utilises.

- **Connexion** : numéro de compte, mot de passe, serveur ; ou « utiliser le compte déjà ouvert dans MT5 ».
  Le **mot de passe n'est jamais enregistré ni journalisé** ; seuls le numéro et le serveur sont mémorisés (`accounts.json`).
- **Changer de compte / se déconnecter** : menu du compte en haut à droite, ou page Comptes. Impossible tant que le bot tourne.
- **Tableau de bord** : état du bot, capital du compte, gains, positions, graphique interactif, activité récente.
  **Démarrer le bot** (confirmation demandée ; un compte réel est refusé) et **Arrêter**.
- Pages **Positions**, **Journal** (filtres signaux / refus / erreurs, recherche), **Bilan** (30 jours, par marché), **Réglages**
  (risque, positions max, arrêt du jour, spread max : `settings.json`, pris en compte au prochain démarrage du bot).
- Thème sombre ou clair (bouton en haut). Le bot tourne dans un processus à part ; quitter le tableau de bord (Ctrl+C) l'arrête,
  mais les stop-loss restent chez le broker. Un seul bot qui trade à la fois (détecté automatiquement).
- Sécurité : écoute seulement sur 127.0.0.1, jeton secret à chaque lancement, en-tête Host vérifié, trading demandé avec confirmation.

## Utilisation en ligne de commande

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
- Les lots sont calculés sur le **vrai capital du compte** (option avancée `CAPITAL_CAP` dans `config.py` : un nombre fixe un capital fictif + gains/pertes du bot).
- **3 positions max**, une seule par marché (`MAX_POSITIONS`, réglable dans l'interface). **Arrêt du jour** si le capital baisse de 3 %.
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
python test_dashboard.py           # tableau de bord : sécurité (jeton, Host), connexion, réglages, démarrage/arrêt du bot
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
- Nombre de positions : la simulation (`python sweep_risk.py`) donnait une baisse moyenne un peu plus faible avec **2** qu'avec 3 dans les 6 combinaisons testées ;
  5 est nettement pire. Réglage actuel : **3** (choix de l'utilisateur) ; à 100 $ avec 2 positions : +10 % sur l'année, pire baisse −57 % ; avec 3 : +19 %, −72 %.
- Les autres écarts entre réglages (risque 0,5/1/2 %, capital 100/250/500/1000 $) sont du bruit : ne pas optimiser dessus.
- C'est un **test**, pas une source de revenu : lancer en démo 2 à 3 mois sans toucher aux réglages, puis comparer avec `python report.py`.

## Limites

- Backtest sur 1 an : la 1re moitié était proche de zéro, la 2e très positive. Aucun avantage stable n'est prouvé.
- Avec 100 $, beaucoup de marchés sont refusés (lot minimum trop gros) : Volatility 10/25/50/100, Step Index, l'or.
- Les bougies jour/semaine de MT5 suivent l'heure du serveur du broker, légèrement différente des données du backtest.
- L'échelle mensuelle de la vidéo n'est pas implémentée.
