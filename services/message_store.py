"""
services/message_store.py
Mémoire des messages pour les logs : le contenu ET une copie des pièces jointes.

Pourquoi ce module existe : quand un message est supprimé, Discord n'envoie au bot
que son identifiant s'il n'est plus dans le cache mémoire (les ~1000 derniers
messages, vidé à chaque redémarrage). Et il efface les fichiers joints en même
temps que le message : l'URL de l'image ne répond plus dès la suppression. Pour
pouvoir montrer ce qui a été supprimé, il faut donc tout garder au moment où le
message est posté.

- contenu : SQLite, data/messages.db
- pièces jointes : copiées dans data/attachments/<id_message>/, 8 Mo max par
  fichier (au-delà le bot ne pourrait de toute façon pas les renvoyer), 1 Go au
  total ; au-delà, on garde seulement le nom et la taille
- tout est effacé au bout de RETENTION_JOURS
"""

import asyncio
import json
import os
import shutil
import sqlite3
import threading
import time

_BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(_BASE, "data")
DB_PATH = os.path.join(DATA_DIR, "messages.db")
FICHIERS_DIR = os.path.join(DATA_DIR, "attachments")

RETENTION_JOURS = 7
TAILLE_MAX_FICHIER = 8 * 1024 * 1024
TAILLE_MAX_TOTALE = 1024 * 1024 * 1024

_db = None
_lock = threading.Lock()
_taille_connue = None     # octets occupés par les copies ; recalculé après chaque ménage
_taches = set()           # garde une référence : sinon Python peut abandonner la tâche en route


def _conn():
    global _db
    if _db is None:
        os.makedirs(DATA_DIR, exist_ok=True)
        os.makedirs(FICHIERS_DIR, exist_ok=True)
        db = sqlite3.connect(DB_PATH, check_same_thread=False)
        db.execute("PRAGMA journal_mode=WAL")
        db.execute(
            "CREATE TABLE IF NOT EXISTS messages ("
            " id INTEGER PRIMARY KEY, guild_id INTEGER, channel_id INTEGER,"
            " author_id INTEGER, author_tag TEXT, content TEXT, attachments TEXT,"
            " reply_to INTEGER, created_at REAL)"
        )
        db.execute("CREATE INDEX IF NOT EXISTS idx_messages_date ON messages(created_at)")
        db.commit()
        _db = db
    return _db


def _dossier(message_id: int) -> str:
    return os.path.join(FICHIERS_DIR, str(message_id))


def _taille_dossier() -> int:
    total = 0
    for racine, _d, fichiers in os.walk(FICHIERS_DIR):
        for f in fichiers:
            try:
                total += os.path.getsize(os.path.join(racine, f))
            except OSError:
                pass
    return total


# ── écriture ────────────────────────────────────────────────────────────────

def _inserer(row: tuple):
    with _lock:
        db = _conn()
        with db:
            db.execute("INSERT OR REPLACE INTO messages VALUES (?,?,?,?,?,?,?,?,?)", row)


def _maj(message_id: int, content, attachments):
    with _lock:
        db = _conn()
        with db:
            if attachments is None:
                db.execute("UPDATE messages SET content = ? WHERE id = ?", (content, message_id))
            else:
                db.execute("UPDATE messages SET content = ?, attachments = ? WHERE id = ?",
                           (content, json.dumps(attachments, ensure_ascii=False), message_id))


def _meta_pj(attachment, locale: bool) -> dict:
    return {
        "id": attachment.id,
        "filename": attachment.filename,
        "size": attachment.size,
        "content_type": attachment.content_type or "",
        "url": attachment.url,
        "local": locale,
    }


async def enregistrer(message) -> None:
    """À appeler pour chaque message posté (on_message)."""
    pjs = [_meta_pj(a, False) for a in message.attachments]
    reply = message.reference.message_id if message.reference else None
    row = (message.id, message.guild.id, message.channel.id, message.author.id, str(message.author),
           message.content or "", json.dumps(pjs, ensure_ascii=False), reply,
           message.created_at.timestamp())
    await asyncio.to_thread(_inserer, row)
    if message.attachments:
        # téléchargement en arrière-plan : ne ralentit jamais le traitement du message
        tache = asyncio.create_task(_copier_pieces_jointes(message.id, message.attachments))
        _taches.add(tache)
        tache.add_done_callback(_taches.discard)


async def _copier_pieces_jointes(message_id: int, attachments) -> None:
    global _taille_connue
    dossier = _dossier(message_id)
    pjs = []
    for a in attachments:
        locale = False
        if a.size <= TAILLE_MAX_FICHIER:
            try:
                if _taille_connue is None:
                    _taille_connue = await asyncio.to_thread(_taille_dossier)
                if _taille_connue + a.size <= TAILLE_MAX_TOTALE:
                    os.makedirs(dossier, exist_ok=True)
                    await a.save(os.path.join(dossier, f"{a.id}_{a.filename}"))
                    _taille_connue += a.size
                    locale = True
            except Exception as e:  # réseau, disque : on garde au moins les métadonnées
                print(f"[logs] copie de {a.filename} impossible : {e}")
        pjs.append(_meta_pj(a, locale))
    row = await lire(message_id)
    if row is not None:
        await asyncio.to_thread(_maj, message_id, row["content"], pjs)


async def modifier(message_id: int, content: str, attachments=None) -> None:
    """Met à jour la version gardée après une édition. `attachments` : liste des
    pièces jointes encore présentes (métadonnées), ou None si inchangées."""
    await asyncio.to_thread(_maj, message_id, content, attachments)


# ── lecture ─────────────────────────────────────────────────────────────────

def _lire(message_id: int):
    with _lock:
        cur = _conn().execute("SELECT * FROM messages WHERE id = ?", (message_id,))
        r = cur.fetchone()
    if r is None:
        return None
    return {
        "id": r[0], "guild_id": r[1], "channel_id": r[2], "author_id": r[3],
        "author_tag": r[4], "content": r[5], "attachments": json.loads(r[6] or "[]"),
        "reply_to": r[7], "created_at": r[8],
    }


async def lire(message_id: int):
    return await asyncio.to_thread(_lire, message_id)


async def lire_plusieurs(ids) -> dict:
    out = {}
    for i in ids:
        r = await lire(i)
        if r is not None:
            out[i] = r
    return out


def chemin_fichier(message_id: int, pj: dict):
    """Chemin local de la copie d'une pièce jointe, ou None si elle n'a pas été gardée."""
    if not pj.get("local"):
        return None
    p = os.path.join(_dossier(message_id), f"{pj['id']}_{pj['filename']}")
    return p if os.path.exists(p) else None


# ── ménage ──────────────────────────────────────────────────────────────────

def _oublier(message_id: int):
    with _lock:
        db = _conn()
        with db:
            db.execute("DELETE FROM messages WHERE id = ?", (message_id,))
    shutil.rmtree(_dossier(message_id), ignore_errors=True)


async def oublier(message_id: int) -> None:
    """Après avoir journalisé une suppression : les fichiers sont désormais
    hébergés par Discord dans le salon de logs, inutile de les garder."""
    await asyncio.to_thread(_oublier, message_id)


def _purger() -> int:
    limite = time.time() - RETENTION_JOURS * 86400
    with _lock:
        db = _conn()
        ids = [r[0] for r in db.execute("SELECT id FROM messages WHERE created_at < ?", (limite,))]
        with db:
            db.execute("DELETE FROM messages WHERE created_at < ?", (limite,))
    for i in ids:
        shutil.rmtree(_dossier(i), ignore_errors=True)
    return len(ids)


async def purger() -> int:
    global _taille_connue
    n = await asyncio.to_thread(_purger)
    _taille_connue = None
    return n
