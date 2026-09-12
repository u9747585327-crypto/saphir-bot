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
AUTO_ROLE_NAME = "MEMBER"

# fichier où sont stockés les réglages par serveur (ex : rôle Membre choisi via /set-role-membre)
GUILD_SETTINGS_FILE = "data/guild_settings.json"

# nom du rôle donné pendant qu'un membre est connecté à un salon vocal (doit déjà exister)
VOICE_ROLE_NAME = "En vocal"

# communauté : catégorie d'accueil + salons de vie du serveur. Chaque entrée est
# (nom canonique, lecture_seule, mots-clés) — les mots-clés servent à ADOPTER un salon
# existant proche (le renommer au lieu d'en créer un doublon), voir services/setup_kit.py
COMMUNITY_CATEGORY_NAME = "💠 COMMUNAUTÉ"
COMMUNITY_CHANNELS = [
    ("📢・annonces", True, ["annonce", "annonces", "news"]),
    ("👋・bienvenue", True, ["bienvenue", "welcome", "arrivee"]),
    ("📜・règlement", True, ["reglement", "regles", "rules"]),
    ("💬・général", False, ["general", "chat", "discussion", "tchat"]),
    ("🎮・jeux", False, ["jeux", "gaming", "game", "zonedeguerre", "guerre"]),
    ("📸・partage", False, ["partage", "screen", "media", "photos", "clips"]),
    ("🤖・commandes-bot", False, ["commande", "commandes", "bot", "cmd"]),
]

# hub de salons vocaux temporaires
VOICE_HUB_CATEGORY_NAME = "🔊 VOCAL"
VOICE_HUB_CHANNEL_NAME = "➕・Créer un salon"
VOICE_HUB_INFO_CHANNEL_NAME = "🎧・infos-vocal"

# nom exact du salon-piège anti-bot : quiconque y écrit est expulsé (placé dans la
# catégorie Communauté au setup s'il elle existe)
HONEYPOT_CHANNEL_NAME = "🍯・ne-pas-écrire-ici"

# prison (Alcatraz)
PRISON_CATEGORY_NAME = "🔒 ALCATRAZ"
PRISON_TEXT_CHANNEL = "💬・cellule"
PRISON_VOICE_CHANNEL = "🔇 Isolement"
PRISON_INFO_CHANNEL_NAME = "🔒・infos-alcatraz"
PRISON_SANCTIONS_CHANNEL_NAME = "📋・sanctions"
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
    ("OWNER", 0xE74C3C, {"administrator": True}),
    ("ADMIN", 0x3498DB, {
        "ban_members": True, "kick_members": True, "manage_roles": True, "manage_channels": True,
        "manage_guild": True, "moderate_members": True, "manage_messages": True,
        "mute_members": True, "deafen_members": True, "move_members": True,
    }),
    ("MODERATOR", 0xF1C40F, {
        "kick_members": True, "moderate_members": True, "manage_messages": True,
        "mute_members": True, "deafen_members": True, "move_members": True,
    }),
    ("MEMBER", 0x2ECC71, {}),
]

# rangs de la hiérarchie qui doivent voir Alcatraz et les Logs (en plus du bypass
# automatique des détenteurs de la permission Administrateur)
STAFF_ROLE_NAMES = ["OWNER", "ADMIN", "MODERATOR"]

# hub d'administration : catégorie + salon de commandes réservé à tout rang au-dessus de
# Membre (donc HIERARCHY_ROLES sans son dernier élément), + salon expliquant la hiérarchie
ADMIN_CATEGORY_NAME = "🛠️ ADMINISTRATION"
ADMIN_COMMAND_CHANNEL_NAME = "🛠️・commandes-staff"
ADMIN_INFO_CHANNEL_NAME = "📖・infos-rôles"

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
