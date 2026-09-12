BOT_NAME = "Saphir"

COLORS = {
    "saphir": 0x1F6FEB,
    "gold": 0xF0C258,
    "danger": 0xED4245,
    "success": 0x3BA55D,
    "grey": 0x99AAB5,
}

SCAN_DIR = "data/scans"

# --- style des noms de salons : 「 emoji 」 nom -------------------------------------------
# Discord transforme les espaces normaux en tirets dans les salons texte (et met en
# minuscules). On utilise l'espace Braille U+2800, que Discord conserve tel quel, pour
# obtenir un vrai espacement « 「 🔥 」 annonces ». Astuce classique des serveurs aesthetic.
_S = "⠀"


def _ch(emoji: str, name: str) -> str:
    return f"「{_S}{emoji}{_S}」{_S}{name}"


# nom du rôle donné automatiquement à l'arrivée d'un membre, utilisé seulement si aucun rôle
# n'a été choisi via /set-role-membre (doit déjà exister sur le serveur pour servir de secours)
AUTO_ROLE_NAME = "𝗠𝗲𝗺𝗯𝗿𝗲"

# fichier où sont stockés les réglages par serveur (ex : rôle Membre choisi via /set-role-membre)
GUILD_SETTINGS_FILE = "data/guild_settings.json"

# nom du rôle donné pendant qu'un membre est connecté à un salon vocal (doit déjà exister)
VOICE_ROLE_NAME = "En vocal"

# deux catégories gérées par cogs/community.py. Chaque salon est (nom canonique,
# lecture_seule, mots-clés) — les mots-clés servent à ADOPTER un salon existant proche
# (le renommer au lieu d'en créer un doublon), voir services/setup_kit.py.
#
# INFOS : lecture seule (annonces + règlement).
INFOS_CATEGORY_NAME = "📢 INFOS"
INFOS_CHANNELS = [
    (_ch("📢", "annonces"), True, ["annonce", "annonces", "news"]),
    (_ch("📜", "règlement"), True, ["reglement", "regles", "rules"]),
]
# COMMUNAUTÉ : salons de discussion où les membres peuvent écrire.
COMMUNITY_CATEGORY_NAME = "💬 COMMUNAUTÉ"
COMMUNITY_CHANNELS = [
    (_ch("💬", "général"), False, ["general", "chat", "discussion", "tchat"]),
    (_ch("🎮", "jeux"), False, ["jeux", "gaming", "game"]),
    (_ch("📸", "médias"), False, ["medias", "media", "partage", "screen", "clips"]),
    (_ch("🤖", "commandes-bot"), False, ["commande", "commandes", "cmd"]),
]

# compteurs statistiques : salons vocaux verrouillés dont le nom s'auto-met à jour.
# {count} est remplacé par le nombre. Les IDs créés sont mémorisés dans guild_settings.
STATS_CATEGORY_NAME = "📈 STATISTIQUES"
STATS_CHANNELS = [
    ("members", "👥 Membres : {count}", ["membre", "members"]),
    ("boosts", "🚀 Boosts : {count}", ["boost", "boosts"]),
]
STATS_REFRESH_SECONDS = 600  # Discord limite le renommage d'un salon (~2 fois / 10 min)

# anti-raid : détection d'une vague d'arrivées (join flood)
ANTIRAID_JOIN_COUNT = 5            # nombre d'arrivées...
ANTIRAID_JOIN_WINDOW = 10          # ...dans cette fenêtre (secondes) => raid détecté
ANTIRAID_MODE_DURATION = 300       # durée du mode raid après détection (secondes)
ANTIRAID_MIN_ACCOUNT_AGE_DAYS = 7  # pendant un raid, les comptes plus jeunes sont expulsés

# hub de salons vocaux temporaires
VOICE_HUB_CATEGORY_NAME = "🔊 VOCAL"
VOICE_HUB_CHANNEL_NAME = _ch("➕", "créer-un-salon")
VOICE_HUB_INFO_CHANNEL_NAME = _ch("🎧", "infos-vocal")

# nom du salon-piège anti-bot : quiconque y écrit est expulsé (placé dans la catégorie
# INFOS au setup si elle existe)
HONEYPOT_CHANNEL_NAME = _ch("🍯", "ne-pas-écrire-ici")

# prison (Alcatraz)
PRISON_CATEGORY_NAME = "🔒 ALCATRAZ"
PRISON_TEXT_CHANNEL = _ch("💬", "cellule")
PRISON_VOICE_CHANNEL = _ch("🔇", "isolement")
PRISON_INFO_CHANNEL_NAME = _ch("🔒", "infos-alcatraz")
PRISON_SANCTIONS_CHANNEL_NAME = _ch("📋", "sanctions")
EXILE_ROLE_NAME = "⛓️ Exilé"
PRISON_DATA_FILE = "data/prison.json"

# logs serveur
LOGS_CATEGORY_NAME = "📋 LOGS"
LOG_CHANNELS = {
    "join_leave": _ch("📥", "arrivées-départs"),
    "moderation": _ch("🔨", "modération"),
    "voice": _ch("🎙️", "vocal"),
    "profile": _ch("✏️", "pseudos-avatars"),
    "messages": _ch("💬", "messages"),
    "roles": _ch("🎭", "rôles"),
    "channels": _ch("📁", "salons"),
    "server": _ch("⚙️", "serveur"),
}

# niveaux (XP texte + vocal cumulés)
LEVELS_DATA_FILE = "data/levels.json"
LEVELS_CATEGORY_NAME = "📊 NIVEAUX"
LEVEL_UP_CHANNEL_NAME = _ch("🎉", "niveaux")
LEADERBOARD_CHANNEL_NAME = _ch("🏆", "classement")
LEVELS_INFO_CHANNEL_NAME = _ch("📊", "infos-niveaux")
LEADERBOARD_REFRESH_SECONDS = 300

# paliers de rôles automatiques : (niveau requis, nom du rôle, couleur)
# stockés par ID dans data/guild_settings.json une fois créés, donc renommables sans risque
LEVEL_ROLES = [
    (5, "🌱 𝗗𝗲𝗯𝘂𝘁𝗮𝗻𝘁", 0x2ECC71),
    (10, "🌿 𝗔𝗰𝘁𝗶𝗳", 0x1ABC9C),
    (20, "🌳 𝗩𝗲𝘁𝗲𝗿𝗮𝗻", 0x3498DB),
    (35, "⭐ 𝗘𝗹𝗶𝘁𝗲", 0x9B59B6),
    (50, "👑 𝗟𝗲𝗴𝗲𝗻𝗱𝗲", 0xF1C40F),
]

# hiérarchie de rôles visibles (hoist), permissions Discord natives cumulées,
# du plus haut rang au plus bas — noms en police grasse sans-serif (rendue nativement
# par Discord, aucune police externe requise)
HIERARCHY_ROLES = [
    ("𝗙𝗼𝗻𝗱𝗮𝘁𝗲𝘂𝗿", 0x9B59B6, {"administrator": True}),
    ("𝗖𝗼-𝗙𝗼𝗻𝗱𝗮𝘁𝗲𝘂𝗿", 0x8E44AD, {
        "ban_members": True, "kick_members": True, "manage_roles": True, "manage_channels": True,
        "manage_guild": True, "moderate_members": True, "manage_messages": True,
        "mention_everyone": True, "mute_members": True, "deafen_members": True, "move_members": True,
    }),
    ("𝗔𝗱𝗺𝗶𝗻", 0xE67E22, {
        "ban_members": True, "kick_members": True, "manage_channels": True,
        "moderate_members": True, "manage_messages": True, "mention_everyone": True,
        "mute_members": True, "deafen_members": True, "move_members": True,
    }),
    ("𝗠𝗼𝗱𝗲𝗿𝗮𝘁𝗲𝘂𝗿", 0xF1C40F, {
        "kick_members": True, "moderate_members": True, "manage_messages": True,
        "mention_everyone": True, "mute_members": True, "deafen_members": True, "move_members": True,
    }),
    ("𝗠𝗲𝗺𝗯𝗿𝗲", 0x2ECC71, {}),
]

# rangs de la hiérarchie qui doivent voir Alcatraz et les Logs (en plus du bypass
# automatique des détenteurs de la permission Administrateur)
STAFF_ROLE_NAMES = ["𝗙𝗼𝗻𝗱𝗮𝘁𝗲𝘂𝗿", "𝗖𝗼-𝗙𝗼𝗻𝗱𝗮𝘁𝗲𝘂𝗿", "𝗔𝗱𝗺𝗶𝗻", "𝗠𝗼𝗱𝗲𝗿𝗮𝘁𝗲𝘂𝗿"]

# hub d'administration : catégorie + salon de commandes réservé à tout rang au-dessus de
# Membre (donc HIERARCHY_ROLES sans son dernier élément), + salon expliquant la hiérarchie
ADMIN_CATEGORY_NAME = "🛠️ ADMINISTRATION"
ADMIN_COMMAND_CHANNEL_NAME = _ch("🛠️", "commandes-staff")
ADMIN_INFO_CHANNEL_NAME = _ch("📖", "infos-rôles")

# rôles de permission autonomes, indépendants du rang, pour débloquer /jail et /unjail
PERM_JAIL_ROLE_NAME = "「🜲・⛓️ Perm Jail」"
PERM_UNJAIL_ROLE_NAME = "「🜲・🔓 Perm Unjail」"

# casier : petit historique par membre des vannes de l'IA à son sujet, réutilisé pour
# des piques qui rappellent un running gag précédent (continuité au lieu de vannes jetables)
DOSSIER_DATA_FILE = "data/dossiers.json"
DOSSIER_MAX_ENTRIES = 10  # entrées conservées par membre, les plus anciennes sont supprimées

# lien compte Discord <-> tag Brawl Stars (voir cogs/brawlstars.py)
BRAWLSTARS_LINKS_FILE = "data/brawlstars_links.json"
# proxy RoyaleAPI par défaut : contourne le verrou par IP de l'API officielle (l'IP de sortie
# de Render change à chaque redéploiement, donc une clé verrouillée dessus casserait sans arrêt)
BRAWLSTARS_API_BASE = "https://bsproxy.royaleapi.dev/v1"
BRAWLSTARS_CATEGORY_NAME = "🎮 BRAWL STARS"
BRAWLSTARS_INFO_CHANNEL_NAME = "🎮・brawl-stars-info"

FUNCHAT_MENTION_RESPONSES = [
    "Ouais je suis là, calme-toi 😌",
    "Quoi encore ?",
    "Présent ! (malheureusement)",
    "Tu m'as appelé ? Flatté.",
    "Oui chef, qu'est-ce qu'il y a ?",
]
