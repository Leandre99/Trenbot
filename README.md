# TrendBot - Bot d'alertes & signaux Deriv

Bot d'alertes et de signaux de trading pour **Deriv** (sans MT5, sans PC allumé en permanence).
Il surveille les marchés et envoie des notifications en direct sur ton téléphone (**Telegram** ou **ntfy**).

---

## Marchés surveillés

- **Or (XAU/USD)** : `frxXAUUSD`
- **Step Index** : `stpRNG`
- **Indices de Volatilité standard** :
  - Volatility 10 (`R_10`),15 (`R_15`) 25 (`R_25`), 50 (`R_50`), 75 (`R_75`), 100 (`R_100`)
- **Indices de Volatilité 1 seconde (1s)** :
  - Volatility 10 (1s) (`1HZ10V`), 15 (1s) (`1HZ15V`), 25 (1s) (`1HZ25V`), 50 (1s) (`1HZ50V`), 75 (1s) (`1HZ75V`), 100 (1s) (`1HZ100V`)

*(Toutes les paires de devises Forex ont été retirées).*

---

## Stratégie (à la clôture de chaque bougie)

- **Achat** : La MM8 croise la MM21 vers le haut, **puis** la MM8, la MM21 et le prix cassent la MM50 vers le haut. Le signal part à la clôture de cette cassure (cassure dans les 30 bougies suivant le croisement). Le **RSI 14** confirme s'il a touché ou frôlé la zone de survente (35 ou moins).
- **Vente** : Symétrique (croisement vers le bas, cassure de la MM50 vers le bas, RSI vers 70).
- **Gestion proposée** : Stop de protection (plus bas / plus haut des 10 dernières bougies) et Objectif à 2R (2 fois la distance au stop).

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
