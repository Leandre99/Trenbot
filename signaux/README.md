# Bot de signaux (sans MT5, sans ton PC)

Il **ne prend aucune position**. Il surveille les marchés et t'envoie une **notification sur ton téléphone** quand
ta stratégie donne un signal. C'est toi qui décides de trader.

**Stratégie** (à la clôture de chaque bougie) :
- **Achat** : le RSI 14 est passé sous 30 (survente) dans les 20 dernières bougies, puis la MM8 passe au-dessus de la
  MM21, les deux au-dessus de la MM50, et le prix clôture au-dessus de la MM50.
- **Vente** : l'inverse (RSI au-dessus de 70, MM8 sous la MM21, les deux sous la MM50, prix sous la MM50).
- La notification propose un **stop** (plus bas / plus haut des 10 dernières bougies) et un **objectif** (2 fois le risque).

Données : API publique de Deriv (aucun compte, aucun mot de passe). Notifications : **Telegram** (ou l'application gratuite ntfy).

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
| `unites` | unités de temps : `M1`, `M5`, `M15`, `M30`, `H1`, `H4`, `D1` |
| `mm_rapide`, `mm_moyenne`, `mm_lente` | 8, 21, 50 |
| `rsi_periode`, `rsi_bas`, `rsi_haut` | 14, 30, 70 |
| `rsi_memoire` | la survente / le surachat doit dater de moins de N bougies (20) |
| `stop_bougies`, `objectif_r` | stop proposé sur N bougies (10) ; objectif = N fois le risque (2, ou 0 pour aucun) |
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
