import json
import os

_MONGO_URI = os.environ.get("MONGODB_URI")
_collection = None

if _MONGO_URI:
    try:
        from pymongo import MongoClient

        _client = MongoClient(_MONGO_URI, serverSelectionTimeoutMS=5000)
        _client.admin.command("ping")
        _collection = _client["saphir"]["kv_store"]
        print("💾 Stockage : connecté à MongoDB")
    except Exception as e:
        print(f"⚠️ MONGODB_URI fourni mais connexion impossible ({e}) — repli sur les fichiers JSON locaux")
        _collection = None


def is_connected() -> bool:
    """True si le stockage utilise MongoDB, False s'il utilise les fichiers JSON locaux."""
    return _collection is not None


def load_json(path, default):
    """Charge la donnée enregistrée sous `path` (base Mongo si configurée, sinon fichier local)."""
    if _collection is not None:
        doc = _collection.find_one({"_id": path})
        return doc["data"] if doc else default

    if not os.path.exists(path):
        return default
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def save_json(path, data):
    """Enregistre `data` sous `path` (base Mongo si configurée, sinon fichier local)."""
    if _collection is not None:
        _collection.replace_one({"_id": path}, {"_id": path, "data": data}, upsert=True)
        return

    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def list_json(directory):
    """Liste les clés enregistrées sous ce dossier/préfixe (équivalent d'un os.listdir), triées à l'envers."""
    directory = directory.rstrip("/")

    if _collection is not None:
        prefix = directory + "/"
        ids = _collection.distinct("_id", {"_id": {"$regex": f"^{prefix}"}})
        return sorted((i[len(prefix):] for i in ids), reverse=True)

    if not os.path.isdir(directory):
        return []
    return sorted(os.listdir(directory), reverse=True)
