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
LEADERBOARD_REFRESH_SECONDS = 300

# paliers de rôles automatiques : (niveau requis, nom du rôle, couleur)
# stockés par ID dans data/guild_settings.json une fois créés, donc renommables sans risque
LEVEL_ROLES = [
    (5, "🌱 Débutant", 0x2ECC71),
    (10, "🌿 Actif", 0x1ABC9C),
    (20, "🌳 Vétéran", 0x3498DB),
    (35, "⭐ Élite", 0x9B59B6),
    (50, "👑 Légende", 0xF1C40F),
]

# hiérarchie de rôles visibles (hoist), permissions Discord natives cumulées,
# du plus haut rang au plus bas — noms en police grasse sans-serif (rendue nativement
# par Discord, aucune police externe requise)
HIERARCHY_ROLES = [
    ("🌟 𝗙𝗼𝗻𝗱𝗮𝘁𝗲𝘂𝗿", 0xF0C258, {"administrator": True}),
    ("𝗖𝗼-𝗙𝗼𝗻𝗱𝗮𝘁𝗲𝘂𝗿", 0xE74C3C, {
        "ban_members": True, "kick_members": True, "manage_roles": True, "manage_channels": True,
        "manage_guild": True, "moderate_members": True, "manage_messages": True,
        "mute_members": True, "deafen_members": True, "move_members": True,
    }),
    ("𝗖𝗼𝗺𝗺𝗮𝗻𝗱𝗮𝗻𝘁", 0x9B59B6, {
        "kick_members": True, "moderate_members": True, "manage_messages": True,
        "mute_members": True, "deafen_members": True, "move_members": True,
    }),
    ("𝗔𝗱𝗺𝗶𝗻 𝗩𝗼𝗰𝗮𝗹", 0x3498DB, {"mute_members": True, "deafen_members": True, "move_members": True}),
    ("𝗔𝗱𝗺𝗶𝗻 𝗖𝗵𝗮𝘁", 0x1ABC9C, {"manage_messages": True}),
    ("✨ 𝗠𝗲𝗺𝗯𝗿𝗲", 0xC9C3E0, {}),
]

# rangs de la hiérarchie qui doivent voir Alcatraz et les Logs (en plus du bypass
# automatique des détenteurs de la permission Administrateur)
STAFF_ROLE_NAMES = ["🌟 𝗙𝗼𝗻𝗱𝗮𝘁𝗲𝘂𝗿", "𝗖𝗼-𝗙𝗼𝗻𝗱𝗮𝘁𝗲𝘂𝗿", "𝗖𝗼𝗺𝗺𝗮𝗻𝗱𝗮𝗻𝘁"]

# rôles de permission autonomes, indépendants du rang, pour débloquer /jail et /unjail
PERM_JAIL_ROLE_NAME = "⛓️ Perm Jail"
PERM_UNJAIL_ROLE_NAME = "🔓 Perm Unjail"
