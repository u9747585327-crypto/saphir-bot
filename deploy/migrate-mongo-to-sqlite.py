#!/usr/bin/env python3
"""
Migration MongoDB -> SQLite pour Saphir.

A lancer UNE FOIS sur le VPS, avant de retirer MONGODB_URI du .env :

    cd /opt/<dossier-du-bot>
    MONGODB_URI="<l-uri-atlas>" .venv/bin/python deploy/migrate-mongo-to-sqlite.py

Le script lit tout ce qui est dans Atlas et l'ecrit dans la base SQLite locale.
Il ne supprime rien cote Atlas : en cas de probleme, il suffit de remettre
MONGODB_URI dans le .env pour revenir en arriere.
"""

import json
import os
import sqlite3
import sys

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.environ.get("STORAGE_DB") or os.path.join(BASE_DIR, "data", "saphir.db")

uri = os.environ.get("MONGODB_URI") or (sys.argv[1] if len(sys.argv) > 1 else None)
if not uri:
    sys.exit("MONGODB_URI manquante : passe-la en variable d'environnement ou en argument.")

try:
    from pymongo import MongoClient
except ImportError:
    sys.exit("pymongo n'est pas installe. Lance le script avec le python du venv : .venv/bin/python")

print("Connexion a MongoDB...")
client = MongoClient(uri, serverSelectionTimeoutMS=8000)
client.admin.command("ping")

collection = client["saphir"]["kv_store"]
pairs = []
for doc in collection.find({}):
    key = doc["_id"]
    pairs.append((key, doc.get("data")))
    print("  - " + str(key))

if not pairs:
    sys.exit("Rien a migrer : la base Mongo est vide (verifie l'URI et le nom de la base).")

os.makedirs(os.path.dirname(DB_PATH) or ".", exist_ok=True)
conn = sqlite3.connect(DB_PATH)
conn.execute("PRAGMA journal_mode=WAL")
conn.execute("PRAGMA synchronous=FULL")
conn.execute("CREATE TABLE IF NOT EXISTS kv (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
conn.commit()

existing = conn.execute("SELECT COUNT(*) FROM kv").fetchone()[0]
if existing and "--force" not in sys.argv:
    sys.exit(
        f"La base {DB_PATH} contient deja {existing} entree(s).\n"
        "Relance avec --force pour les ecraser avec les donnees d'Atlas."
    )

with conn:
    for key, data in pairs:
        conn.execute(
            "INSERT OR REPLACE INTO kv (key, value) VALUES (?, ?)",
            (key, json.dumps(data, ensure_ascii=False)),
        )

total = conn.execute("SELECT COUNT(*) FROM kv").fetchone()[0]
conn.close()

print(f"\nOK : {len(pairs)} entree(s) migree(s), {total} au total dans {DB_PATH}")
print("Tu peux maintenant retirer MONGODB_URI du .env puis redemarrer le service.")
