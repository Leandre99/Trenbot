# Bot de signaux (sans MT5, sans ton PC)

> **En service : GitHub Actions** (`.github/workflows/signaux.yml`, toutes les 5 min, dépôt public = gratuit).
> Secrets du dépôt : `TELEGRAM_TOKEN` et `TELEGRAM_CHAT_ID` (Settings → Secrets and variables → Actions).
> Essai : Actions → signaux → Run workflow → cocher « Envoyer seulement un message d'essai ».
> GitHub lance ses passages programmés très irrégulièrement (2 en 11 h le premier soir) : le worker Cloudflare
> (`cloudflare/worker.js`) sert d'horloge et demande un passage à GitHub à :01 :16 :31 :46. Secret Cloudflare :
> `GITHUB_TOKEN` (jeton GitHub fine-grained, dépôt Trenbot, droit « Actions : Read and write »).

Il **ne prend aucune position**. Il surveille les marchés et t'envoie une **notification sur ton téléphone** quand
ta stratégie donne un signal. C'est toi qui décides de trader.

**Stratégie** (sur la bougie en cours, sans attendre sa clôture : `attendre_cloture`) :
- **Achat** : la MM8 croise la MM21 vers le haut, **puis** la MM8, la MM21 et le prix (clôture d'une bougie) cassent la MM50 vers le haut : le signal
  part à la clôture de cette cassure (un seul signal par croisement ; la cassure doit suivre le croisement de
  30 bougies au plus). Le **RSI 14 confirme** s'il a touché ou frôlé 30 (35 ou moins) avant : ce n'est pas obligatoire,
  le message dit si c'est confirmé (`rsi_obligatoire` pour l'exiger).
- **Vente** : l'inverse (croisement vers le bas, cassure de la MM50 vers le bas, RSI vers 70).
- La notification (courte : Prix, SL, TP) propose un **SL** et un **TP**, chacun à **1,5 ATR** du prix (ATR 14).

Données : API publique de Deriv (aucun compte, aucun mot de passe). Notifications : **Telegram** (ou l'application gratuite ntfy).

## Trading automatique (M15 et M30)

Le bot peut **prendre lui-même les positions** des signaux **M15 et M30** sur Deriv (contrats *Multipliers*), avec
le SL et le TP du message (1,5 ATR). Code : `trading.py`. **Arrêté par défaut.**

**Commandes Telegram** (seulement depuis ta discussion, prises en compte au passage suivant, 15 min au plus) :
`/demarrer` : prend les prochains signaux ; `/arreter` : n'en prend plus (les positions ouvertes restent ouvertes) ;
`/etat` : état et réglages.

**Messages** : trading arrêté → les signaux arrivent comme d'habitude. Trading démarré → chaque signal porte en plus une ligne
`Position : PRISE : mise …, risque … (2.0 %)` ou `Position : NON PRISE : <raison>` (H1/H4 : jamais pris automatiquement).

**Règles** (`trading_auto` dans `signaux.py`) :
- perte au SL (commission comprise) = **2 % du solde** du compte au moment du trade ;
- si les minimums de Deriv (mise 1 $, SL et TP à 0,10 $ minimum, multiplicateurs imposés) obligent à risquer plus,
  jusqu'à **3 %** ; au-delà, le trade est **sauté** (message Telegram avec la raison) ;
- le SL est toujours placé avant le « stop out » de Deriv (perte de toute la mise) ;
- **3 positions maximum** par compte, jamais deux sur le même marché ;
- avant d'acheter, le bot demande un prix à Deriv et vérifie que les niveaux de SL et TP renvoyés correspondent à ceux du message.

> Avec un **petit compte** (10 $), la plupart des signaux seront sautés : sur les Volatility et le Step Index, le
> plus petit trade possible risque 0,40 à 0,70 $, soit 4 à 7 % de 10 $. Il faut environ **25 $ ou plus** pour que
> les trades passent à 2-3 %. **Commence sur le compte démo.**

**Mise en place** (secrets GitHub : Settings → Secrets and variables → Actions) :
1. Sur **developers.deriv.com** : crée une application de type **PAT** → tu obtiens un **App ID**. Secret `DERIV_APP_ID`.
2. Dans le tableau de bord, section **API tokens** : crée un jeton avec le droit **trade** uniquement (pas de retrait).
   Il n'est affiché qu'une fois.
3. Note l'identifiant du compte (démo ou réel) à utiliser.
4. Secret `DERIV_COMPTES` (un ou plusieurs comptes) :
   ```json
   [{"nom": "demo", "compte": "IDENTIFIANT_DU_COMPTE", "jeton": "TON_JETON"}]
   ```
5. Sur Telegram, envoie `/etat` pour vérifier, puis `/demarrer`.

Les comptes rendus (positions prises, sautées et pourquoi) arrivent sur Telegram ; les journaux GitHub (publics)
n'affichent aucun montant.

## 1. Sur ton téléphone : Telegram

1. Dans Telegram, cherche **@BotFather**, appuie sur **Démarrer**, puis envoie `/newbot`.
2. Donne-lui un nom (ex. `Mes signaux`) puis un identifiant finissant par `bot` (ex. `mes_signaux_123_bot`).
3. BotFather te répond avec un **jeton** du type `123456789:AAH...`. **Ne le partage avec personne** : il donne le
   contrôle de ton bot.
4. Ouvre ton nouveau bot (lien donné par BotFather) et appuie sur **Démarrer**.
5. Sur la machine où tourne le bot de signaux : `python3 signaux.py --telegram`, colle le jeton. Il trouve ta
   discussion tout seul, l'enregistre dans `config.json` (jamais envoyé sur GitHub) et t'envoie un message d'essai.

Sans Telegram, le bot utilise **ntfy** (application gratuite, sans compte) : abonne-toi au canal `signaux-xxxx`
affiché au démarrage.

## 2. Réglages (`config.json`, créé au premier lancement)

| Clé | Rôle |
|---|---|
| `marches` | nom affiché -> code Deriv (`frxEURUSD`, `frxXAUUSD`, `R_75`, `stpRNG`…) |
| `unites` | unités de temps de tous les marchés : `M1`, `M5`, `M15`, `M30`, `H1`, `H4`, `D1` (par défaut `M15`, `M30`, `H1`, `H4`) |
| `unites_marche` | exceptions par marché (nom affiché -> unités). Par défaut `{}` (aucune). Exemple : `{"Or": ["M15", "M30", "H1", "H4"]}` |
| `mm_rapide`, `mm_moyenne`, `mm_lente` | 8, 21, 50 |
| `rsi_periode`, `rsi_bas`, `rsi_haut` | 14, 30, 70 |
| `attendre_cloture` | `false` (par défaut) : analyse aussi la bougie en cours, signal plus tôt mais il peut disparaître ; `true` : bougies terminées seulement |
| `rsi_memoire` | fenêtre du RSI : de N bougies avant le croisement MM8/MM21 jusqu'à maintenant (50) |
| `sl_tp_mode` | `"atr"` (par défaut) ou `"bougies"` (ancien calcul) |
| `atr_periode`, `sl_atr`, `tp_atr` | mode `atr` : ATR 14 ; SL à 1,5 ATR ; TP à 1,5 ATR (0 pour aucun) |
| `stop_bougies`, `objectif_r` | mode `bougies` : SL sur N bougies (10) ; TP = N fois le risque (2, ou 0 pour aucun) |
| `ntfy_canal` | ton canal privé (nom au hasard : ne le partage pas) |

Après une modification, redémarre le bot (`sudo systemctl restart signaux` sur le serveur).

## 3. Sur Oracle Cloud (gratuit, tourne jour et nuit)

1. Crée un compte sur **cloud.oracle.com** (offre *Always Free* ; la carte sert seulement à vérifier ton identité).
2. **Compute → Instances → Create instance** : image **Ubuntu**, forme *Always Free* (VM.Standard.E2.1.Micro ou
   Ampere A1). Télécharge la **clé SSH** proposée. Crée.
3. Connecte-toi (depuis le terminal de ton PC, avec l'adresse IP publique affichée par Oracle) :
   ```
   ssh -i chemin/vers/la-cle.key ubuntu@ADRESSE_IP
   ```
4. Sur le serveur, copie-colle :
   ```
   sudo apt update && sudo apt install -y python3-pip git
   git clone https://github.com/Leandre99/Trenbot.git
   cd Trenbot/signaux
   pip3 install --break-system-packages -r requirements.txt
   python3 signaux.py --telegram
   ```
   (Si le dépôt est privé, GitHub demande ton identifiant et un *jeton d'accès* à la place du mot de passe.)
   `--telegram` te demande le jeton de @BotFather et t'envoie un message d'essai sur Telegram.
5. Pour qu'il tourne en permanence (et redémarre tout seul) :
   ```
   sudo cp signaux.service /etc/systemd/system/
   sudo systemctl enable --now signaux
   ```
   Voir ce qu'il fait : `tail -f signaux.log`. L'arrêter : `sudo systemctl stop signaux`.

## Sur ton PC (pour essayer)

```
pip install -r requirements.txt
python signaux.py --once --sans-notif     # un passage, n'envoie rien
python signaux.py --test                  # notification d'essai
python signaux.py                         # en continu
python test_signaux.py                    # tests
```
