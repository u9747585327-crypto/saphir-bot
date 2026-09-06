"""Client de l'API Brawl Stars — aucune dépendance à Discord.

Séparé du cog pour que la couche Discord (commandes, popups, embeds) n'ait plus qu'à
appeler des fonctions d'ici. La clé est nettoyée au chargement : un copier-coller de JWT
embarque souvent un retour à la ligne, qu'aiohttp refuse ensuite avec « Forbidden control
character detected in headers » — bug réellement rencontré en production.
"""

import asyncio
import os

import aiohttp

from config import BRAWLSTARS_API_BASE

API_KEY = (os.environ.get("BRAWLSTARS_API_KEY") or "").strip() or None
API_BASE = os.environ.get("BRAWLSTARS_API_BASE", BRAWLSTARS_API_BASE).strip()

VALID_TAG_CHARS = set("0289PYLQGRJCUV")
REQUEST_TIMEOUT = 10
PARALLEL_BATCH = 8  # requêtes simultanées max pour le classement

# Le CDN Brawlify est public, sans clé ni verrou d'IP, et sert les images que l'API
# officielle ne fournit pas (elle ne renvoie qu'un identifiant d'icône).
ICON_CDN = "https://cdn.brawlify.com/profile-icons/regular/{}.png"
BADGE_CDN = "https://cdn.brawlify.com/club-badges/regular/{}.png"

ERROR_MESSAGES = {
    "not_configured": "🔌 La clé API Brawl Stars n'est pas configurée sur le bot.",
    "not_found": "❌ Tag introuvable — vérifie l'orthographe (visible dans le jeu, sous ton pseudo).",
    "forbidden": (
        "❌ Clé API refusée par Supercell. Vérifie qu'elle est bien verrouillée sur l'IP du "
        "proxy RoyaleAPI (45.79.218.79), pas sur l'IP du serveur."
    ),
    "rate_limited": "⏳ Trop de requêtes vers l'API Brawl Stars, réessaie dans une minute.",
    "network": "❌ Impossible de joindre l'API Brawl Stars (réseau).",
}


def is_configured() -> bool:
    return bool(API_KEY)


def normalize_tag(raw: str) -> str:
    """Nettoie un tag saisi par un humain et l'encode pour l'URL : l'API attend %23 au lieu
    de #, sinon aiohttp lirait le # comme un début de fragment et tronquerait le tag."""
    tag = raw.strip().upper().lstrip("#").replace(" ", "")
    return "%23" + tag


def display_tag(raw: str) -> str:
    return normalize_tag(raw).replace("%23", "#")


def tag_is_plausible(raw: str) -> bool:
    tag = raw.strip().upper().lstrip("#").replace(" ", "")
    return 3 <= len(tag) <= 14 and all(c in VALID_TAG_CHARS for c in tag)


def error_message(error: str) -> str:
    return ERROR_MESSAGES.get(error, f"❌ Erreur API Brawl Stars ({error}).")


def icon_url(icon_id):
    return ICON_CDN.format(icon_id) if icon_id else None


def badge_url(badge_id):
    return BADGE_CDN.format(badge_id) if badge_id else None


async def _request(session: aiohttp.ClientSession, path: str):
    """Retourne (data, erreur) — erreur vaut None en cas de succès."""
    try:
        async with session.get(f"{API_BASE}/{path}", timeout=aiohttp.ClientTimeout(total=REQUEST_TIMEOUT)) as resp:
            if resp.status == 200:
                return await resp.json(), None
            if resp.status == 404:
                return None, "not_found"
            if resp.status == 403:
                return None, "forbidden"
            if resp.status == 429:
                return None, "rate_limited"
            return None, f"http_{resp.status}"
    except (aiohttp.ClientError, TimeoutError) as e:
        print(f"⚠️ Erreur réseau Brawl Stars ({path}) : {e}")
        return None, "network"
    except Exception as e:
        # filet : une erreur inattendue (JSON invalide...) ne doit pas remonter en silence
        print(f"⚠️ Erreur inattendue Brawl Stars ({path}) : {type(e).__name__}: {e}")
        return None, "network"


async def get(path: str):
    """Un appel unique. Retourne (data, erreur)."""
    if not API_KEY:
        return None, "not_configured"
    headers = {"Authorization": f"Bearer {API_KEY}"}
    async with aiohttp.ClientSession(headers=headers) as session:
        return await _request(session, path)


async def get_player(tag: str):
    return await get(f"players/{normalize_tag(tag)}")


async def get_club(tag: str):
    return await get(f"clubs/{normalize_tag(tag)}")


async def get_players_bulk(tags: list) -> dict:
    """Récupère plusieurs joueurs par paquets parallèles plutôt qu'un par un — le
    classement enchaînait autant d'allers-retours que de comptes liés, en série.
    Retourne {tag: data} en ignorant silencieusement les tags en échec."""
    if not API_KEY or not tags:
        return {}

    results = {}
    headers = {"Authorization": f"Bearer {API_KEY}"}
    async with aiohttp.ClientSession(headers=headers) as session:
        for start in range(0, len(tags), PARALLEL_BATCH):
            batch = tags[start:start + PARALLEL_BATCH]
            responses = await asyncio.gather(
                *(_request(session, f"players/{normalize_tag(tag)}") for tag in batch)
            )
            for tag, (data, error) in zip(batch, responses):
                if error is None:
                    results[tag] = data
    return results
