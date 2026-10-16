"""
storage.py
Stockage clé/valeur du bot : niveaux/XP, heures vocales, peines, casiers, réglages
par serveur, scans...

Deux backends possibles, choisis automatiquement au démarrage :

1. **SQLite** (par défaut) — un seul fichier `data/saphir.db` sur le disque du serveur.
   Écritures atomiques et transactionnelles : même si le bot est tué en plein milieu
   (reboot, OOM, systemctl restart), la base n'est jamais laissée à moitié écrite.
   C'est le mode normal depuis la migration sur le VPS.
2. **MongoDB** — utilisé uniquement si `MONGODB_URI` est définie. Conservé pour pouvoir
   rebasculer sur une base distante sans toucher au code.

L'ancien mode « un fichier JSON par clé » a été remplacé : il réécrivait le fichier
entier après l'avoir tronqué, ce qui pouvait le corrompre en cas d'arrêt brutal, et deux
écritures simultanées pouvaient se mélanger. Les anciens fichiers `data/*.json` sont
importés automatiquement dans SQLite au premier démarrage, rien n'est perdu.
"""

import asyncio
import json
import os
import sqlite3
import threading

_BASE_DIR = os.path.dirname(os.path.abspath(__file__))
_DATA_DIR = os.path.join(_BASE_DIR, "data")
_DB_PATH = os.environ.get("STORAGE_DB") or os.path.join(_DATA_DIR, "saphir.db")

_MONGO_URI = os.environ.get("MONGODB_URI")
_collection = None

_db = None
_db_lock = threading.Lock()


def _key(path) -> str:
    """Normalise une clé : les séparateurs Windows deviennent des '/' pour que la même
    donnée soit retrouvée quel que soit l'OS."""
    return str(path).replace("\\", "/")


# ── Initialisation du backend ────────────────────────────────────────────────

def _import_legacy_json(conn):
    """Premier démarrage sur SQLite : recopie les anciens fichiers data/**.json dans la
    base, puis les laisse en place (on ne supprime rien — filet de sécurité)."""
    if not os.path.isdir(_DATA_DIR):
        return

    imported = 0
    for root, _dirs, files in os.walk(_DATA_DIR):
        for name in files:
            if not name.endswith(".json"):
                continue
            full = os.path.join(root, name)
            key = _key(os.path.relpath(full, _BASE_DIR))
            try:
                with open(full, "r", encoding="utf-8") as f:
                    data = json.load(f)
            except (OSError, ValueError) as e:
                print(f"⚠️ Import ignoré pour {key} (fichier illisible : {e})")
                continue
            conn.execute(
                "INSERT OR REPLACE INTO kv (key, value) VALUES (?, ?)",
                (key, json.dumps(data, ensure_ascii=False)),
            )
            imported += 1

    if imported:
        print(f"💾 {imported} ancien(s) fichier(s) JSON importé(s) dans SQLite")


def _init_sqlite():
    global _db
    os.makedirs(os.path.dirname(_DB_PATH) or ".", exist_ok=True)
    conn = sqlite3.connect(_DB_PATH, check_same_thread=False)
    # WAL : un lecteur ne bloque pas un écrivain, et la base reste cohérente si le
    # process meurt. synchronous=FULL : chaque commit est réellement sur le disque.
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=FULL")
    conn.execute("CREATE TABLE IF NOT EXISTS kv (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
    conn.commit()

    if conn.execute("SELECT COUNT(*) FROM kv").fetchone()[0] == 0:
        _import_legacy_json(conn)
        conn.commit()

    _db = conn
    print(f"💾 Stockage : SQLite ({_DB_PATH})")


if _MONGO_URI:
    try:
        from pymongo import MongoClient

        _client = MongoClient(_MONGO_URI, serverSelectionTimeoutMS=5000)
        _client.admin.command("ping")
        _collection = _client["saphir"]["kv_store"]
        print("💾 Stockage : connecté à MongoDB")
    except Exception as e:
        print(f"⚠️ MONGODB_URI fourni mais connexion impossible ({e}) — repli sur SQLite")
        _collection = None

if _collection is None:
    _init_sqlite()


def backend() -> str:
    """Nom du backend réellement utilisé, pour l'afficher dans /diagnostic."""
    return "MongoDB" if _collection is not None else "SQLite"


def is_connected() -> bool:
    """True si le stockage utilise MongoDB. Conservé pour compatibilité ; le stockage
    SQLite est tout aussi durable, voir backend()."""
    return _collection is not None


# ── API publique (inchangée) ─────────────────────────────────────────────────

def load_json(path, default):
    """Charge la donnée enregistrée sous `path`."""
    key = _key(path)

    if _collection is not None:
        doc = _collection.find_one({"_id": key})
        return doc["data"] if doc else default

    with _db_lock:
        row = _db.execute("SELECT value FROM kv WHERE key = ?", (key,)).fetchone()
    return json.loads(row[0]) if row else default


def save_json(path, data):
    """Enregistre `data` sous `path`. L'écriture SQLite est atomique : en cas d'arrêt
    brutal, c'est l'ancienne valeur qui reste, jamais une valeur à moitié écrite."""
    key = _key(path)

    if _collection is not None:
        _collection.replace_one({"_id": key}, {"_id": key, "data": data}, upsert=True)
        return

    payload = json.dumps(data, ensure_ascii=False)
    with _db_lock:
        with _db:  # transaction : commit automatique, rollback si erreur
            _db.execute("INSERT OR REPLACE INTO kv (key, value) VALUES (?, ?)", (key, payload))


async def aload_json(path, default):
    """Version non bloquante de load_json : l'appel part dans un thread pour ne pas geler
    la boucle d'événements du bot (à utiliser dans les chemins chauds : à chaque message,
    boucles périodiques...)."""
    return await asyncio.to_thread(load_json, path, default)


async def asave_json(path, data):
    """Version non bloquante de save_json (voir aload_json)."""
    await asyncio.to_thread(save_json, path, data)


def list_json(directory):
    """Liste les clés enregistrées sous ce dossier/préfixe (équivalent d'un os.listdir),
    triées à l'envers."""
    prefix = _key(directory).rstrip("/") + "/"

    if _collection is not None:
        ids = _collection.distinct("_id", {"_id": {"$regex": f"^{prefix}"}})
        return sorted((i[len(prefix):] for i in ids), reverse=True)

    with _db_lock:
        rows = _db.execute("SELECT key FROM kv").fetchall()
    # filtrage par prefixe cote Python : evite d'avoir a echapper les caracteres
    # speciaux de LIKE ('%' et '_') dans des cles qui viennent de noms de fichiers.
    return sorted(
        (r[0][len(prefix):] for r in rows if r[0].startswith(prefix)),
        reverse=True,
    )
