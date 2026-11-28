# TrenBot MT5 (Expert Advisor)

`TrenBot.mq5` prend **lui-même les positions** dans MetaTrader 5, avec **exactement la même stratégie** que le bot
de signaux (`signaux/signaux.py`). Une vérification sur 14 400 fenêtres de bougies réelles a donné 0 différence
(sens, SL et TP).

| | |
|---|---|
| Signal | MM8 croise MM21, puis MM8, MM21 et prix cassent la MM50 (bougie en cours, sans attendre la clôture) ; croisement de 30 bougies au plus ; un seul signal par croisement |
| SL / TP | 1,5 ATR(14) chacun, ATR de Wilder sur les 200 dernières bougies |
| Unités | **M15 et M30** |
| Taille | perte au SL = **2 % du solde** ; si le lot minimum oblige à plus, jusqu'à **3 %**, sinon trade sauté |
| Limites | **3 positions** au plus, jamais deux sur le même symbole ; une seule tentative par bougie |
| SL/TP trop proches | jamais déplacés : trade sauté, avec la raison sur Telegram |

## Telegram

Depuis ta discussion avec ton bot (seulement elle) : **`/demarrer`**, **`/arreter`**, **`/etat`** (accents acceptés).
Réponse en moins d'une minute. **Arrêté au premier lancement.**

Messages envoyés par le robot :
- à chaque signal (trading démarré) : sens, symbole, prix, SL, TP et `Position : PRISE : lot …, risque … (2.0 %)`
  ou `Position : NON PRISE : <raison>` ;
- à chaque fermeture : `TP touché` / `SL touché`, résultat et nouveau solde.

Le bot de signaux sur GitHub continue d'envoyer ses signaux de son côté (toutes unités).

## Installation (sur le serveur Windows)

1. Installe **MT5 depuis le site de Deriv** et connecte-toi à ton compte (démo pour commencer).
2. Dans MT5 : **Fichier → Ouvrir le dossier des données** → `MQL5\Experts` → copie `TrenBot.mq5` dedans.
3. **Outils → MetaQuotes Language Editor** (F4), ouvre `TrenBot.mq5`, puis **Compiler** (F7) : 0 erreur attendue.
4. **Outils → Options → Expert Advisors** : coche **Autoriser le trading algorithmique** et
   **Autoriser WebRequest pour les URL suivantes**, ajoute `https://api.telegram.org`.
5. Ouvre n'importe quel graphique (par exemple Volatility 75 Index, M15), fais glisser **TrenBot** dessus.
   Onglet **Paramètres d'entrée** : `InpTgToken` = jeton du bot Telegram, `InpTgChat` = identifiant de ta discussion
   (les mêmes que pour le bot de signaux). Onglet **Commun** : coche **Autoriser le trading algorithmique**.
6. Active le bouton **Algo Trading** (vert) dans la barre d'outils.
7. Tu reçois « TrenBot lancé… » sur Telegram. Envoie `/etat`, vérifie « Symboles trouvés : 13/13 »,
   puis `/demarrer`.

Si des symboles sont « introuvables », recopie leur nom exact depuis la **Surveillance du marché** de MT5 dans le
paramètre `InpSymbols`.

## Mettre à jour le robot (double-clic)

Une seule fois : télécharge **`MAJ-TrenBot.bat`** (dossier `mt5` sur GitHub) et mets-le sur le **Bureau du serveur**.
Ensuite, à chaque nouvelle version : **double-clic sur `MAJ-TrenBot.bat`**. Il télécharge la dernière version de
`TrenBot.mq5`, la place dans `MQL5\Experts` et la compile ; MT5 recharge le robot tout seul. Une fenêtre affiche
`OK : TrenBot est à jour` (ou l'erreur de compilation à envoyer).

## À savoir

- MT5 doit rester **ouvert** sur le serveur (ferme la fenêtre Bureau à distance sans te déconnecter de Windows :
  croix de la fenêtre, pas « Se déconnecter »).
- Le robot garde son état (marche/arrêt) même si MT5 redémarre.
- Rien n'est garanti : le backtest sur plusieurs mois tournait autour de zéro. **Commence sur le compte démo.**
