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
LEVEL_UP_CHANNEL_NAME = "🎉・niveaux"
