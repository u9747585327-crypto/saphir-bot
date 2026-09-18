# Hébergement de Saphir — comment tout est branché

Doc de référence pour recréer la même stack ailleurs si besoin. Trois services externes,
tous gratuits, tous indépendants du code (rien n'est codé en dur — tout passe par des
variables d'environnement).

## 1. Le bot lui-même — Render.com (Web Service, plan gratuit)

- Compte sur [render.com](https://render.com), connecté au dépôt GitHub
  `u9747585327-crypto/saphir-bot`.
- Type de service : **Web Service** (pas "Background Worker" — le plan gratuit exige un
  port HTTP ouvert, voir point 3).
- Build command : `pip install -r requirements.txt`
- Start command : `python main.py`
- Version Python fixée par `runtime.txt` (`python-3.12.7`) — Render la lit automatiquement.
- **Variables d'environnement à renseigner sur Render** (Settings → Environment) :
  - `DISCORD_TOKEN` — le token du bot, dans le Developer Portal Discord de l'application.
  - `MONGODB_URI` — voir point 2.
  - `GROQ_API_KEY` — clé API Groq, pour le chat IA (`console.groq.com`).
  - `PORT` — Render la fournit tout seul, pas besoin de la définir à la main.
- **Limite du plan gratuit** : le service s'endort après 15 minutes sans requête HTTP
  entrante. Un bot Discord ne reçoit pas ce genre de requête tout seul → il faut le
  "pinguer" de l'extérieur (point 3), sinon il se déconnecte de Discord au bout d'un moment.
- Chaque `git push` sur la branche déployée redéploie automatiquement.

## 2. La base de données — MongoDB Atlas (Free Tier, cluster M0)

- Compte sur [mongodb.com/cloud/atlas](https://www.mongodb.com/cloud/atlas), cluster gratuit
  (M0, 512 Mo — largement suffisant pour ce bot).
- Sert à stocker tout ce qui doit survivre à un redémarrage : niveaux/XP, heures vocales,
  peines Alcatraz, casiers, réglages par serveur (rôles, salons mémorisés par ID)...
- Accès réseau : sur Atlas, autoriser `0.0.0.0/0` (Network Access → Add IP Address →
  "Allow access from anywhere") — l'IP de sortie de Render change à chaque redéploiement,
  impossible de la fixer.
- Récupérer la chaîne de connexion (Connect → Drivers → Python) et la coller telle quelle
  dans la variable `MONGODB_URI` sur Render — remplacer `<password>` par le vrai mot de passe
  de l'utilisateur de base de données créé sur Atlas.
- **Filet de sécurité intégré dans le code** (`storage.py`) : si `MONGODB_URI` est absente ou
  que la connexion échoue au démarrage, le bot bascule tout seul sur des fichiers JSON
  locaux dans `data/`. Ça permet de tester en local sans base — mais sur Render, ces
  fichiers sont perdus à chaque redéploiement (le disque n'est pas persistant), donc en
  production `MONGODB_URI` doit toujours être configurée.

## 3. Le "ping" anti-veille — UptimeRobot

- Compte gratuit sur [uptimerobot.com](https://uptimerobot.com).
- Un monitor **HTTP(s)** créé, pointant vers l'URL publique du service Render
  (ex. `https://saphir-bot.onrender.com`), avec un intervalle de **5 minutes**
  (le minimum du plan gratuit — largement en dessous des 15 min avant mise en veille).
- Côté bot, cette URL répond grâce à un petit serveur web interne (`keep_alive.py`,
  Flask + waitress) lancé en parallèle du bot Discord : une route `/` qui répond juste
  "Saphir est en ligne." UptimeRobot n'a besoin de rien d'autre — un simple 200 OK.
- Sans ce ping, Render met le service en veille après 15 min d'inactivité HTTP, et le bot
  disparaît de Discord (hors ligne) jusqu'à la prochaine requête qui le réveille (ce qui
  prend 30-60 s).

## Schéma global

```
Discord ⇄ Bot (Render, plan gratuit)
              │
              ├── stocke/lit ses données ⇄ MongoDB Atlas (M0 gratuit)
              │
              └── expose une route HTTP "/" ⇐ ping toutes les 5 min ⇐ UptimeRobot
```

## Pour en recréer un autre

1. Nouveau repo GitHub avec le code.
2. Nouveau Web Service Render pointant dessus, avec les 3 variables d'environnement
   (`DISCORD_TOKEN`, `MONGODB_URI`, `GROQ_API_KEY`).
3. Nouveau cluster M0 sur Atlas (ou une base à part dans le même cluster existant — Atlas
   permet plusieurs bases par cluster), accès réseau `0.0.0.0/0`.
4. Nouveau monitor UptimeRobot sur l'URL Render du nouveau service.

Aucun de ces 3 services ne connaît l'existence des autres — ils communiquent uniquement via
les variables d'environnement (URL, token, URI) que tu configures toi-même. Rien à
recréer côté code.
