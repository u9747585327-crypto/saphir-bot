# Hébergement de Saphir — comment tout est branché

Tout tourne sur un seul VPS IONOS : le bot et ses données. Aucun service externe, aucun
compte à renouveler, rien qui puisse tomber en panne de son côté.

> **Historique** : le bot tournait sur Render.com (plan gratuit) avec MongoDB Atlas comme
> base et UptimeRobot pour l'empêcher de s'endormir. Tout a été rapatrié sur le VPS.
> Render n'héberge plus rien.

## 1. Le bot — VPS IONOS (systemd)

Un VPS Linux (Ubuntu 22.04+ ou Debian 12) chez IONOS, accessible en SSH. Le bot tourne
comme un service systemd : il démarre avec la machine et redémarre tout seul s'il plante.

**Installation, en une commande sur le VPS :**

```bash
ssh root@<ip-du-vps>
git clone https://github.com/u9747585327-crypto/saphir-bot.git /tmp/saphir-src
sudo bash /tmp/saphir-src/deploy/install-ionos.sh
```

Le script [deploy/install-ionos.sh](deploy/install-ionos.sh) fait tout :

- installe `git`, `python3`, `python3-venv` ;
- crée un utilisateur système `saphir-bot` sans shell (le bot ne tourne pas en root) ;
- clone le code dans `/opt/saphir-bot` ;
- crée l'environnement virtuel `.venv` et installe `requirements.txt` ;
- crée un `.env` vide en `chmod 600` (jamais écrasé si déjà présent) ;
- installe et active le service [deploy/saphir-bot.service](deploy/saphir-bot.service).

**Variables à renseigner dans `/opt/saphir-bot/.env`** :

| Variable | Obligatoire | Où la trouver |
|---|---|---|
| `DISCORD_TOKEN` | oui | Developer Portal Discord → ton application → onglet Bot |
| `GROQ_API_KEY` | oui | [console.groq.com](https://console.groq.com) — pour le chat IA |
| `MONGODB_URI` | **non** | à laisser commentée : le stockage est local (voir point 2) |

Puis `systemctl start saphir-bot`.

**Dans le Developer Portal Discord**, onglet Bot : activer les **Privileged Gateway
Intents** `Server Members Intent` et `Message Content Intent` — le code en a besoin
(autorole, logs de messages, leveling).

**Au quotidien :**

```bash
systemctl status saphir-bot        # état du service
journalctl -u saphir-bot -f        # logs en direct
systemctl restart saphir-bot       # redémarrage
sudo bash /opt/saphir-bot/deploy/install-ionos.sh   # mise à jour depuis GitHub
```

Contrairement à Render, **un `git push` ne déploie rien tout seul** : il faut relancer le
script d'installation pour que le VPS prenne le nouveau code.

**Pas besoin d'ouvrir de port dans le pare-feu IONOS.** Un bot Discord n'établit que des
connexions sortantes. Le petit serveur Flask de [keep_alive.py](keep_alive.py) écoute
toujours sur le port 8080, mais il ne sert plus à rien ici (voir point 3).

## 2. Les données — SQLite, sur le VPS

Tout est dans **un seul fichier** : `/opt/saphir-bot/data/saphir.db`. Niveaux/XP, heures
vocales, peines Alcatraz, casiers, réglages par serveur, scans. Pas de serveur de base de
données à installer, pas de RAM consommée, pas de compte externe : SQLite est inclus dans
Python.

**Pourquoi SQLite et pas des fichiers JSON** : l'ancien repli JSON réécrivait le fichier
entier après l'avoir tronqué (`open(path, "w")`). Si le bot était tué au mauvais moment —
reboot, `systemctl restart`, OOM — le fichier restait à moitié écrit et les données
étaient perdues. Avec le leveling qui écrit à chaque message, le risque était réel. SQLite
écrit dans une transaction : en cas d'arrêt brutal, c'est l'ancienne valeur qui reste,
jamais une valeur corrompue. Le mode WAL et `synchronous=FULL` sont activés dans
[storage.py](storage.py).

**Reprise de l'existant** : au premier démarrage, s'il traîne encore des `data/*.json`
d'une version précédente, ils sont importés automatiquement dans la base, puis laissés en
place (rien n'est supprimé). Un fichier illisible est ignoré avec un avertissement, sans
faire planter le bot.

**Sauvegarde** — un fichier à copier, donc un cron suffit :

```bash
# sauvegarde quotidienne à 4h, 14 jours d'historique
0 4 * * * sqlite3 /opt/saphir-bot/data/saphir.db ".backup '/root/backups/saphir-$(date +\%F).db'" && find /root/backups -name 'saphir-*.db' -mtime +14 -delete
```

(`.backup` de sqlite3 est sûr même pendant que le bot écrit, contrairement à un `cp`.)

**Et si tu veux une base distante un jour** : renseigne `MONGODB_URI` dans le `.env` et le
code rebascule sur MongoDB sans aucune modification. Le script
[deploy/migrate-mongo-to-sqlite.py](deploy/migrate-mongo-to-sqlite.py) fait le trajet
inverse (Atlas → SQLite), c'est lui qui a servi à la migration.

## 3. Le "ping" anti-veille — supprimé

Plus nécessaire, et c'est le principal gain de la migration. Render mettait le service en
veille après 15 min sans requête HTTP, ce qui obligeait à le réveiller toutes les 5 min
avec un monitor UptimeRobot. Un VPS ne dort jamais : le process tourne en continu, et
systemd le relance s'il tombe. Le monitor UptimeRobot peut être supprimé.

## Schéma global

```
Discord ⇄ Bot (VPS IONOS, service systemd, 24/7)
              │
              └── lit/écrit ⇄ data/saphir.db (SQLite, même machine)
```

Une seule machine, une seule chose à surveiller.

## Pour en recréer un autre

1. Repo GitHub avec le code.
2. VPS IONOS (Ubuntu/Debian), puis `sudo bash deploy/install-ionos.sh` — en adaptant
   `NAME`, `REPO` et le bloc `.env` en haut du script, ainsi que le fichier `.service`.
3. Remplir le `.env`, `systemctl start`. Rien d'autre : la base se crée toute seule.

Plusieurs bots peuvent cohabiter sur le même VPS : chacun son dossier `/opt/<nom>`, son
utilisateur système, son `.env`, son service systemd et sa base SQLite.
