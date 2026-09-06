BOT_NAME = "Saphir"

COLORS = {
    "saphir": 0x1F6FEB,
    "gold": 0xF0C258,
    "danger": 0xED4245,
    "success": 0x3BA55D,
    "grey": 0x99AAB5,
}

SCAN_DIR = "data/scans"

# nom du rôle donné automatiquement à l'arrivée d'un membre, utilisé seulement si aucun rôle
# n'a été choisi via /set-role-membre (doit déjà exister sur le serveur pour servir de secours)
AUTO_ROLE_NAME = "Membre"

# fichier où sont stockés les réglages par serveur (ex : rôle Membre choisi via /set-role-membre)
GUILD_SETTINGS_FILE = "data/guild_settings.json"

# nom du rôle donné pendant qu'un membre est connecté à un salon vocal (doit déjà exister)
VOICE_ROLE_NAME = "En vocal"

# hub de salons vocaux temporaires
VOICE_HUB_CATEGORY_NAME = "🎧 VOCAL"
VOICE_HUB_CHANNEL_NAME = "➕ Créer un salon"
VOICE_HUB_INFO_CHANNEL_NAME = "🎧・infos-vocal"

# nom exact du salon-piège anti-bot : quiconque y écrit est expulsé
HONEYPOT_CHANNEL_NAME = "🍯・ne-pas-écrire-ici"

# prison (Alcatraz)
PRISON_CATEGORY_NAME = "🔒 ALCATRAZ"
PRISON_TEXT_CHANNEL = "🔒・cellule"
PRISON_VOICE_CHANNEL = "🔒 Isolement"
EXILE_ROLE_NAME = "⛓️ Exilé"
PRISON_DATA_FILE = "data/prison.json"

# logs serveur
LOGS_CATEGORY_NAME = "📋 LOGS"
LOG_CHANNELS = {
    "join_leave": "📥・arrivées-départs",
    "moderation": "🔨・modération",
    "voice": "🎙️・vocal",
    "profile": "✏️・pseudos-avatars",
    "messages": "💬・messages",
    "roles": "🎭・rôles",
    "channels": "📁・salons",
    "server": "⚙️・serveur",
}

# niveaux (XP texte + vocal cumulés)
LEVELS_DATA_FILE = "data/levels.json"
LEVELS_CATEGORY_NAME = "📊 NIVEAUX"
LEVEL_UP_CHANNEL_NAME = "🎉・niveaux"
LEADERBOARD_CHANNEL_NAME = "🏆・classement"
LEVELS_INFO_CHANNEL_NAME = "📊・infos-niveaux"
LEADERBOARD_REFRESH_SECONDS = 300

# paliers de rôles automatiques : (niveau requis, nom du rôle, couleur)
# stockés par ID dans data/guild_settings.json une fois créés, donc renommables sans risque
LEVEL_ROLES = [
    (5, "「🜲・🌱 𝗗𝗲𝗯𝘂𝘁𝗮𝗻𝘁」", 0x2ECC71),
    (10, "「🜲・🌿 𝗔𝗰𝘁𝗶𝗳」", 0x1ABC9C),
    (15, "「🜲・🔍 𝗢𝗦𝗜𝗡𝗧」", 0x2C3E50),
    (20, "「🜲・🌳 𝗩𝗲𝘁𝗲𝗿𝗮𝗻」", 0x3498DB),
    (35, "「🜲・⭐ 𝗘𝗹𝗶𝘁𝗲」", 0x9B59B6),
    (50, "「🜲・👑 𝗟𝗲𝗴𝗲𝗻𝗱𝗲」", 0xF1C40F),
]

# rôle qui débloque l'accès au salon de recherche de profil Discord (voir cogs/osint.py)
# doit correspondre exactement à un des noms de LEVEL_ROLES ci-dessus
OSINT_ROLE_NAME = "「🜲・🔍 𝗢𝗦𝗜𝗡𝗧」"
OSINT_CATEGORY_NAME = "🔍 RECHERCHE"
OSINT_INFO_CHANNEL_NAME = "🔍・explications"
OSINT_COMMAND_CHANNEL_NAME = "🔍・recherche"
OSINT_DAILY_LIMIT = 5
OSINT_USAGE_FILE = "data/osint_usage.json"

# hiérarchie de rôles visibles (hoist), permissions Discord natives cumulées,
# du plus haut rang au plus bas — noms en police grasse sans-serif (rendue nativement
# par Discord, aucune police externe requise)
HIERARCHY_ROLES = [
    ("「🜲・👑 𝗙𝗼𝗻𝗱𝗮𝘁𝗲𝘂𝗿」", 0xF0C258, {"administrator": True}),
    ("「🜲・𝗖𝗼-𝗙𝗼𝗻𝗱𝗮𝘁𝗲𝘂𝗿」", 0xE74C3C, {
        "ban_members": True, "kick_members": True, "manage_roles": True, "manage_channels": True,
        "manage_guild": True, "moderate_members": True, "manage_messages": True,
        "mute_members": True, "deafen_members": True, "move_members": True,
    }),
    ("「🜲・𝗖𝗼𝗺𝗺𝗮𝗻𝗱𝗮𝗻𝘁」", 0x9B59B6, {
        "kick_members": True, "moderate_members": True, "manage_messages": True,
        "mute_members": True, "deafen_members": True, "move_members": True,
    }),
    ("「🜲・𝗔𝗱𝗺𝗶𝗻 𝗩𝗼𝗰𝗮𝗹」", 0x3498DB, {"mute_members": True, "deafen_members": True, "move_members": True}),
    ("「🜲・𝗔𝗱𝗺𝗶𝗻 𝗖𝗵𝗮𝘁」", 0x1ABC9C, {"manage_messages": True}),
    ("「🜲・✨ 𝗠𝗲𝗺𝗯𝗿𝗲」", 0xC9C3E0, {}),
]

# rangs de la hiérarchie qui doivent voir Alcatraz et les Logs (en plus du bypass
# automatique des détenteurs de la permission Administrateur)
STAFF_ROLE_NAMES = ["「🜲・👑 𝗙𝗼𝗻𝗱𝗮𝘁𝗲𝘂𝗿」", "「🜲・𝗖𝗼-𝗙𝗼𝗻𝗱𝗮𝘁𝗲𝘂𝗿」", "「🜲・𝗖𝗼𝗺𝗺𝗮𝗻𝗱𝗮𝗻𝘁」"]

# rôles de permission autonomes, indépendants du rang, pour débloquer /jail et /unjail
PERM_JAIL_ROLE_NAME = "「🜲・⛓️ Perm Jail」"
PERM_UNJAIL_ROLE_NAME = "「🜲・🔓 Perm Unjail」"

# casier : petit historique par membre des vannes de l'IA à son sujet, réutilisé pour
# des piques qui rappellent un running gag précédent (continuité au lieu de vannes jetables)
DOSSIER_DATA_FILE = "data/dossiers.json"
DOSSIER_MAX_ENTRIES = 10  # entrées conservées par membre, les plus anciennes sont supprimées

FUNCHAT_CATEGORY_NAME = "🤖 CHAT IA"
FUNCHAT_INFO_CHANNEL_NAME = "🤖・infos-chat-ia"

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
