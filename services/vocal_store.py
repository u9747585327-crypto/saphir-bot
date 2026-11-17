"""
services/vocal_store.py
Historique des passages en vocal : qui, dans quel salon, de quand à quand.

Une ligne par passage dans un salon (un changement de salon ferme le passage et en
ouvre un autre). SQLite, data/vocal.db ; gardé RETENTION_JOURS.
"""

import asyncio
import os
import sqlite3
import threading
import time

_BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.path.join(_BASE, "data", "vocal.db")
RETENTION_JOURS = 90

_db = None
_lock = threading.Lock()


def _conn():
    global _db
    if _db is None:
        os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
        db = sqlite3.connect(DB_PATH, check_same_thread=False)
        db.execute("PRAGMA journal_mode=WAL")
        db.execute(
            "CREATE TABLE IF NOT EXISTS sessions ("
            " guild_id INTEGER, user_id INTEGER, channel_id INTEGER, channel_name TEXT,"
            " debut REAL, fin REAL)"
        )
        db.execute("CREATE INDEX IF NOT EXISTS idx_sessions_user ON sessions(guild_id, user_id, debut)")
        db.commit()
        _db = db
    return _db


def _ajouter(row):
    with _lock:
        db = _conn()
        with db:
            db.execute("INSERT INTO sessions VALUES (?,?,?,?,?,?)", row)


async def ajouter(guild_id, user_id, channel_id, channel_name, debut, fin):
    if fin - debut < 1:
        return
    await asyncio.to_thread(_ajouter, (guild_id, user_id, channel_id, channel_name, debut, fin))


def _historique(guild_id, user_id, limite):
    with _lock:
        db = _conn()
        dernieres = db.execute(
            "SELECT channel_id, channel_name, debut, fin FROM sessions WHERE guild_id=? AND user_id=? "
            "ORDER BY debut DESC LIMIT ?", (guild_id, user_id, limite)).fetchall()
        maintenant = time.time()
        totaux = {}
        for jours in (1, 7, 30):
            totaux[jours] = db.execute(
                "SELECT COALESCE(SUM(fin - debut), 0) FROM sessions WHERE guild_id=? AND user_id=? AND debut>=?",
                (guild_id, user_id, maintenant - jours * 86400)).fetchone()[0]
        salons = db.execute(
            "SELECT channel_name, SUM(fin - debut) AS t FROM sessions WHERE guild_id=? AND user_id=? "
            "AND debut>=? GROUP BY channel_id ORDER BY t DESC LIMIT 3",
            (guild_id, user_id, maintenant - 30 * 86400)).fetchall()
    return dernieres, totaux, salons


async def historique(guild_id, user_id, limite=15):
    """(dernières sessions, {1: s, 7: s, 30: s} cumulés, 3 salons les plus fréquentés sur 30 j)."""
    return await asyncio.to_thread(_historique, guild_id, user_id, limite)


def _purger():
    with _lock:
        db = _conn()
        with db:
            db.execute("DELETE FROM sessions WHERE fin < ?", (time.time() - RETENTION_JOURS * 86400,))


async def purger():
    await asyncio.to_thread(_purger)
