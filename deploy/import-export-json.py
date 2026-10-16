#!/usr/bin/env python3
"""
Importe dans SQLite un export JSON recupere depuis l'interface web de MongoDB Atlas.

Utile quand on n'a plus le mot de passe de la base : l'export se fait depuis le
navigateur (Browse Collections -> Export Collection -> JSON), sans aucun identifiant
de base de donnees.

    cd /opt/saphir-bot
    .venv/bin/python deploy/import-export-json.py /root/export.json

Accepte les deux formats produits par Atlas (tableau JSON, ou un document par ligne)
et neutralise les enveloppes EJSON ({"$oid": ...}, {"$numberInt": ...}, ...).
Par defaut le script refuse d'ecraser une base qui contient deja des donnees :
ajouter --force pour passer outre.
"""

import json
import os
import sqlite3
import sys

# Les cles peuvent contenir des emojis (noms de scans) : sur un serveur dont la
# locale n'est pas UTF-8, un simple print() ferait planter le script.
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.environ.get("STORAGE_DB") or os.path.join(BASE_DIR, "data", "saphir.db")

args = [a for a in sys.argv[1:] if not a.startswith("--")]
if not args:
    sys.exit("Usage : python deploy/import-export-json.py <fichier-export.json> [--force]")
src = args[0]
if not os.path.exists(src):
    sys.exit(f"Fichier introuvable : {src}")


def plain(value):
    """Remplace les enveloppes EJSON d'Atlas par des valeurs Python normales."""
    if isinstance(value, dict):
        if len(value) == 1:
            key = next(iter(value))
            if key in ("$numberInt", "$numberLong"):
                return int(value[key])
            if key == "$numberDouble":
                return float(value[key])
            if key in ("$oid", "$symbol"):
                return str(value[key])
            if key == "$date":
                inner = value[key]
                return plain(inner) if isinstance(inner, dict) else inner
        return {k: plain(v) for k, v in value.items()}
    if isinstance(value, list):
        return [plain(v) for v in value]
    return value


with open(src, "r", encoding="utf-8") as f:
    text = f.read().strip()

if not text:
    sys.exit("Le fichier est vide.")

decoder = json.JSONDecoder()

try:
    parsed = json.loads(text)
    docs = parsed if isinstance(parsed, list) else [parsed]
except ValueError:
    # Suite de documents JSON colles bout a bout : c'est ce que donne un
    # copier-coller depuis la vue JSON d'Atlas, en une ligne ou en indente,
    # avec ou sans virgules entre les documents.
    docs = []
    i = 0
    n = len(text)
    while i < n:
        while i < n and (text[i].isspace() or text[i] in ',[]'):
            i += 1
        if i >= n:
            break
        try:
            doc, offset = decoder.raw_decode(text, i)
        except ValueError as e:
            around = ' '.join(text[max(0, i - 40):i + 40].split())
            sys.exit('JSON illisible vers le caractere ' + str(i) + ' : ' + str(e) + ' ... ' + around)
        docs.append(doc)
        i = offset

pairs = []
for doc in docs:
    doc = plain(doc)
    if "_id" not in doc:
        print(f"  ! document sans _id, ignore : {str(doc)[:60]}")
        continue
    key = str(doc["_id"])
    pairs.append((key, doc.get("data")))
    print(f"  - {key}")

if not pairs:
    sys.exit("Aucun document exploitable dans ce fichier.")

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
        "Relance avec --force pour les remplacer par l'export."
    )

with conn:
    for key, data in pairs:
        conn.execute(
            "INSERT OR REPLACE INTO kv (key, value) VALUES (?, ?)",
            (key, json.dumps(data, ensure_ascii=False)),
        )

total = conn.execute("SELECT COUNT(*) FROM kv").fetchone()[0]
conn.close()
print(f"\nOK : {len(pairs)} entree(s) importee(s), {total} au total dans {DB_PATH}")
print("Tu peux demarrer le service.")
