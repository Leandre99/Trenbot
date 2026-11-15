# Bot de signaux sur Cloudflare (gratuit, sans carte, PC éteint)

Cloudflare réveille le bot **chaque minute**. Il regarde les bougies qui viennent de se fermer (M15 une minute après
chaque quart d'heure, H1 deux minutes après l'heure, H4 trois minutes après 0 h, 4 h, 8 h… UTC) et t'envoie un
message **Telegram** si ta stratégie donne un signal. Il ne prend aucune position.

Le code à coller est `worker.js` (les marchés, les unités de temps et les réglages sont en haut du fichier).

## 1. Ton bot Telegram

1. Dans Telegram, **@BotFather** → `/newbot` → un nom → un identifiant finissant par `bot`.
2. Il te donne un **jeton** (`123456789:AAH...`). Garde-le pour toi.
3. Ouvre ton nouveau bot et appuie sur **Démarrer** (ou écris-lui « salut »).
4. Dans ton navigateur, ouvre (en remplaçant `JETON` par ton jeton) :
   `https://api.telegram.org/botJETON/getUpdates`
   Cherche `"chat":{"id":` : le nombre qui suit est ton **identifiant de discussion** (ex. `987654321`).

## 2. Le worker

1. Sur **dash.cloudflare.com** : **Workers & Pages** → **Create** → **Create Worker** (« Hello World ») →
   nom : `signaux` → **Deploy**.
2. **Edit code** : efface tout, colle le contenu de `worker.js`, puis **Deploy**.
3. **Settings → Variables and Secrets → Add** (type **Secret**) :
   - `TELEGRAM_TOKEN` = ton jeton
   - `TELEGRAM_CHAT_ID` = ton identifiant de discussion
4. **Settings → Trigger events (ou Triggers) → Add → Cron Triggers** : `* * * * *` (chaque minute) → **Add**.

## 3. Essai

Ouvre `https://signaux.<ton-sous-domaine>.workers.dev/test?cle=TON_IDENTIFIANT_DE_DISCUSSION` :
tu dois recevoir « 🔔 Essai » sur Telegram. Ensuite, les signaux arrivent tout seuls.

Le journal en direct : dans le worker, **Logs** (ou **Observability**).

## Vérifications faites

- `node test_worker.mjs` : sur de vraies bougies (EUR/USD H1, or M15, Volatility 75 H4, GBP/JPY M30), la version
  Cloudflare donne **exactement les mêmes signaux** que la version Python (`../signaux.py`).
- `node live_check.mjs` : un passage réel sur les données Deriv, sans envoyer de message.
