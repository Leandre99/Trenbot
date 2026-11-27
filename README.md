# TrendBot - Bot d'alertes & signaux Deriv

Bot d'alertes et de signaux de trading pour **Deriv** (sans MT5, sans PC allumé en permanence).
Il surveille les marchés et envoie des notifications en direct sur ton téléphone (**Telegram** ou **ntfy**).

---

## Marchés surveillés

- **Or (XAU/USD)** : `frxXAUUSD`
- **Step Index** : `stpRNG`
- **Indices de Volatilité standard** :
  - Volatility 10 (`R_10`), 25 (`R_25`), 50 (`R_50`), 75 (`R_75`), 100 (`R_100`)
- **Indices de Volatilité 1 seconde (1s)** :
  - Volatility 10 (1s) (`1HZ10V`), 15 (1s) (`1HZ15V`), 25 (1s) (`1HZ25V`), 50 (1s) (`1HZ50V`), 75 (1s) (`1HZ75V`), 100 (1s) (`1HZ100V`)

*(Toutes les paires de devises Forex ont été retirées).*

**Unités de temps** : **M30, H1, H4** pour tous les marchés, plus **M15 pour l'Or uniquement** (réglages `unites` et `unites_marche`, depuis le 26/11/2026 ; avant, M15 était surveillé sur tous les marchés).

---

## Stratégie (sur la bougie en cours, sans attendre sa clôture)

> Depuis le 27/11/2026 (`attendre_cloture: false`), le bot analyse aussi la bougie **pas encore terminée** : le signal part dès que les conditions sont réunies, sans attendre la fin de la bougie. Plus tôt, mais un signal peut **disparaître** si le prix repart avant la clôture. Un seul message par bougie, marché et unité.

- **Achat** : La MM8 croise la MM21 vers le haut, **puis** la **MM8**, la **MM21** et le **prix** (la clôture d'une bougie) cassent la MM50 vers le haut. Le signal part à la clôture de la bougie où les trois sont enfin au-dessus de la MM50.
- **Vente** : Symétrique (croisement MM8/MM21 vers le bas, puis MM8, MM21 et clôture sous la MM50).
- **Conditions conservées** :
  - la MM8 doit rester du bon côté de la MM21 depuis le croisement ;
  - la cassure doit arriver dans les **30 bougies** suivant le croisement (`croisement_max`) ;
  - **un seul signal par croisement** : si le prix a déjà clôturé de l'autre côté de la MM50 depuis le croisement, pas de nouveau signal ;
  - le **RSI 14** confirme s'il est descendu à 35 ou moins (achat) / monté à 65 ou plus (vente), sur une fenêtre allant de 50 bougies avant le croisement jusqu'à maintenant. Non obligatoire par défaut (`rsi_obligatoire`).
- **Gestion proposée** : SL et TP chacun à **1,5 ATR** du prix d'entrée (ATR 14 : taille moyenne des 14 dernières bougies). Réglages : `sl_tp_mode: "atr"`, `atr_periode`, `sl_atr`, `tp_atr` (ancien calcul possible avec `"sl_tp_mode": "bougies"`).
- **Message Telegram** (court) : sens, marché et unité en titre, puis `Prix`, `SL`, `TP`.

---

## Historique des changements de stratégie

### 27/11/2026 : on n'attend plus la clôture des bougies

**Avant** : seules les bougies terminées étaient analysées ; le signal partait à la clôture de la bougie de cassure.

**Après** : la bougie en cours est analysée à chaque passage ; le signal part dès que les conditions sont réunies pendant la bougie. Risque : signal qui n'est plus valable à la clôture (le prix repasse de l'autre côté de la MM50).

**Revenir en arrière** : dans `config.json`, mettre `"attendre_cloture": true` (ou changer la valeur par défaut dans `signaux.py`, nécessaire pour GitHub Actions qui n'a pas de `config.json`).

### 27/11/2026 : retour à la version de départ (MM8, MM21 et prix cassent la MM50)

On revient à la stratégie du commit `da2646f` : la cassure de la MM50 exige à nouveau la **MM8, la MM21 et la clôture**. Le changement du 25/11 « la MM21 n'a plus besoin de casser la MM50 » (plus bas) est **retiré**.
On garde : **SL et TP à 1,5 ATR**, **M15 pour l'Or uniquement** (M30, H1, H4 pour tout le monde) et les **messages courts** (Prix, SL, TP).

### 25/11/2026 : SL et TP à 1,5 ATR

**Avant** : SL = plus bas (achat) / plus haut (vente) des 10 dernières bougies ; TP = 2 fois la distance prix → SL (2R). Signal annulé si le prix était déjà de l'autre côté du SL.

**Après** : SL = prix ∓ 1,5 ATR et TP = prix ± 1,5 ATR (ratio 1:1).

**Pourquoi** : `signaux/backtest.py` (environ 2100 trades par variante, 13 marchés, M15 à H4, jusqu'à 300 jours) a donné le meilleur résultat pour cette variante : 52 % de gagnants, +0,03 R par trade, contre 33 % et −0,01 R pour l'ancien calcul. **Attention** : toutes les variantes testées restaient proches de zéro et le spread n'était pas compté. Ce changement ne rend pas la stratégie gagnante à lui seul.

**Revenir en arrière** : dans `config.json`, mettre `"sl_tp_mode": "bougies"` (l'ancien calcul est gardé, avec `stop_bougies` et `objectif_r`).

### 25/11/2026 : la MM21 n'a plus besoin de casser la MM50

**Avant (version sauvegardée sur la branche `sauvegarde-avant-cassure-prix`, commit `da2646f`)**

Pour un achat, la cassure de la MM50 exigeait que **trois éléments** soient au-dessus de la MM50 sur la bougie du signal (et pas tous les trois sur la bougie d'avant) :
la **MM8**, la **MM21** et le **prix de clôture**. Le signal attendait donc que les moyennes 8 et 21 aient elles aussi cassé la MM50.
Code d'origine dans `signaux/signaux.py`, fonction `detect` :

```python
broke = ((f > s) & (m > s) & (c > s)) if up else ((f < s) & (m < s) & (c < s))
```

**Après (version actuelle)**

Seuls la **MM8** et le **prix de clôture** doivent passer de l'autre côté de la MM50 ; la **MM21** n'est plus exigée :

```python
broke = ((f > s) & (c > s)) if up else ((f < s) & (c < s))
```

Tout le reste est inchangé (croisement MM8/MM21 préalable, 30 bougies max, un seul signal par croisement, RSI, stop, objectif).
Conséquence à connaître : comme la règle « un seul signal par croisement » est gardée, si la MM8 et le prix sont **déjà** au-dessus de la MM50 au moment du croisement 8/21, ce croisement ne donne en pratique pas de signal.

(Étape intermédiaire du même jour, jamais mise en service : on n'exigeait que le prix, `broke = (c > s) if up else (c < s)`. On a remis l'obligation pour la MM8.)

**Revenir en arrière**

- Remettre l'ancienne ligne `broke = ...` ci-dessus dans `detect`, ou
- revenir au code sauvegardé : `git checkout sauvegarde-avant-cassure-prix -- signaux/signaux.py signaux/test_signaux.py`

> Note : le worker Cloudflare (`signaux/cloudflare/worker.js`) contient une ancienne version de la stratégie, mais il ne sert que d'horloge (il déclenche GitHub Actions) : c'est `signaux.py` qui décide des signaux.

---

## Utilisation

### 1. En local sur votre machine
```bash
pip install -r requirements.txt
cd signaux
python signaux.py --once --sans-notif     # Un seul passage d'essai sans envoyer de notif
python signaux.py --test                  # Envoie une notification d'essai
python signaux.py                         # Exécution en continu
```

### 2. Sur Telegram
1. Créez un bot via **@BotFather** sur Telegram et récupérez votre jeton (`token`).
2. Dans le dossier `signaux` :
   ```bash
   python signaux.py --telegram
   ```
3. Collez votre jeton. Le script configure votre discussion automatiquement dans `config.json`.

### 3. Exécution Cloud & 24/7
- **GitHub Actions** ([`.github/workflows/signaux.yml`](.github/workflows/signaux.yml)) : passage programmé toutes les 5 minutes. Renseignez les secrets `TELEGRAM_TOKEN` et `TELEGRAM_CHAT_ID` dans les paramètres de votre dépôt GitHub.
- **Cloudflare Worker** ([`signaux/cloudflare/worker.js`](signaux/cloudflare/worker.js)) : horloge et surveillance ultra-légère.
- **Service Linux (ex. Oracle Cloud Always Free)** : installation via [`signaux/signaux.service`](signaux/signaux.service).

---

## Tests

```bash
python signaux/test_signaux.py
node signaux/cloudflare/test_worker.mjs
```
