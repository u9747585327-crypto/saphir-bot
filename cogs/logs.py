"""
cogs/logs.py
Journal du serveur : QUI a fait QUOI, à QUI, quand, et pourquoi.

Trois sources, chacune pour ce qu'elle sait faire :

1. Le journal d'audit de Discord, reçu en temps réel (on_audit_log_entry_create).
   C'est la seule source qui connaît l'auteur d'une action : qui a donné un rôle,
   qui a mis un timeout, qui a coupé le micro de quelqu'un, qui a touché aux
   permissions d'un salon. Chaque entrée porte l'auteur, la cible, la raison et le
   détail avant/après.

2. Les événements Discord classiques, pour ce que le journal d'audit ignore :
   arrivées, départs, édition de messages, actions faites par un membre sur
   lui-même (couper son propre micro, partager son écran...).

3. Une corrélation entre les deux pour les cas que Discord n'attribue pas tout
   seul : un message supprimé, un membre déplacé ou déconnecté du vocal. L'événement
   ne dit pas qui l'a fait, et l'entrée d'audit correspondante est regroupée
   (« X a supprimé 3 messages de Y ») ; on retrouve l'auteur en suivant
   l'évolution de ces compteurs (voir _Correlateur).

Le contenu et les images des messages supprimés viennent de services/message_store :
Discord efface les fichiers en même temps que le message, il faut les avoir copiés
avant.

Ce que Discord ne transmet jamais au bot, et qu'aucun bot ne peut donc journaliser :
un membre qui rend un autre membre muet « pour lui seul » (clic droit → Rendre muet),
ou qui baisse son volume. C'est un réglage local de son application.

Prérequis : la permission « Voir les logs du serveur » (view_audit_log). Sans elle,
le bot ne voit plus aucun auteur ; il le signale au démarrage.
"""

import asyncio
import datetime
import enum
import io
import re

import discord
from discord import app_commands
from discord.ext import commands, tasks

from config import COLORS, GUILD_SETTINGS_FILE, LOG_CHANNELS, LOGS_CATEGORY_NAME, STAFF_ROLE_NAMES
from services import message_store
from services.setup_kit import adopt_category, adopt_text_channel, find_text_channel, hidden_overwrites
from storage import aload_json, asave_json

A = discord.AuditLogAction

# Un salon de log manquant (ajouté après le dernier /setup-logs) se rabat sur un voisin
# plutôt que de perdre le log.
REPLI = {"permissions": "roles"}


async def resolve_log_channel(bot, guild, key):
    """Retrouve un salon de log par son ID mémorisé (fiable), avec repli sur le nom
    normalisé. Utilisable par les autres cogs (modération, anti-raid) pour ne pas
    dupliquer la logique de recherche."""
    settings = await aload_json(GUILD_SETTINGS_FILE, {})
    cid = settings.get(str(guild.id), {}).get("log_channel_ids", {}).get(key)
    channel = guild.get_channel(cid) if cid else None
    if channel is None:
        channel = find_text_channel(guild, LOG_CHANNELS[key])
    return channel


async def run_setup(bot, guild: discord.Guild) -> list:
    """Logique de /setup-logs, appelable aussi par /setup-tout."""
    report = []
    # invisible pour les membres, MAIS visible pour le staff (Fondateur, Co-Fondateur, Admin,
    # Modérateur) — appliqué sur la catégorie ET chaque salon, sinon les salons gardaient une
    # permission propre qui masquait les logs même au staff non-administrateur
    staff_roles = [r for n in STAFF_ROLE_NAMES if (r := discord.utils.get(guild.roles, name=n))]
    overwrites = hidden_overwrites(guild, *staff_roles)

    category, line = await adopt_category(
        guild, LOGS_CATEGORY_NAME, keywords=["logs", "log"], overwrites=overwrites
    )
    report.append(line)
    if category is None:
        return report

    # on mémorise l'ID de chaque salon de log : les listeners le retrouvent par ID, pas par
    # nom — sinon le moindre écart entre le nom stocké et le nom réel (style 「 」, espaces
    # convertis par Discord…) faisait échouer la recherche et plus aucun log n'était envoyé
    settings = await aload_json(GUILD_SETTINGS_FILE, {})
    log_ids = settings.setdefault(str(guild.id), {}).setdefault("log_channel_ids", {})

    for key, channel_name in LOG_CHANNELS.items():
        channel, line = await adopt_text_channel(
            guild, channel_name, category=category, overwrites=overwrites
        )
        report.append(line)
        if channel is not None:
            log_ids[key] = channel.id

    await asave_json(GUILD_SETTINGS_FILE, settings)
    # invalide le cache mémoire du cog pour qu'il relise les nouveaux IDs
    cog = bot.get_cog("Logs")
    if cog is not None:
        cog._log_ids.pop(guild.id, None)
    return report


# ─────────────────────────────── mise en forme ────────────────────────────────

def _trim(text, limit: int = 1000) -> str:
    if text is None:
        return "*(vide)*"
    text = text if isinstance(text, str) else str(text)
    if not text:
        return "*(vide)*"
    return text if len(text) <= limit else text[: limit - 1] + "…"


PERMS_FR = {
    "administrator": "Administrateur",
    "view_audit_log": "Voir les logs du serveur",
    "view_guild_insights": "Voir les analyses",
    "manage_guild": "Gérer le serveur",
    "manage_roles": "Gérer les rôles et permissions",
    "manage_channels": "Gérer les salons",
    "kick_members": "Expulser",
    "ban_members": "Bannir",
    "moderate_members": "Exclure temporairement (timeout)",
    "create_instant_invite": "Créer une invitation",
    "change_nickname": "Changer son pseudo",
    "manage_nicknames": "Gérer les pseudos",
    "manage_expressions": "Gérer emojis et autocollants",
    "create_expressions": "Créer des emojis",
    "manage_webhooks": "Gérer les webhooks",
    "manage_events": "Gérer les événements",
    "create_events": "Créer des événements",
    "view_channel": "Voir le salon",
    "send_messages": "Envoyer des messages",
    "send_tts_messages": "Messages TTS",
    "manage_messages": "Gérer les messages",
    "pin_messages": "Épingler des messages",
    "embed_links": "Intégrer des liens",
    "attach_files": "Joindre des fichiers",
    "read_message_history": "Voir l'historique",
    "mention_everyone": "Mentionner @everyone",
    "use_external_emojis": "Emojis externes",
    "use_external_stickers": "Autocollants externes",
    "add_reactions": "Réactions",
    "use_application_commands": "Commandes d'applications",
    "use_external_apps": "Applications externes",
    "send_voice_messages": "Messages vocaux",
    "send_polls": "Sondages",
    "manage_threads": "Gérer les fils",
    "create_public_threads": "Créer des fils publics",
    "create_private_threads": "Créer des fils privés",
    "send_messages_in_threads": "Écrire dans les fils",
    "bypass_slowmode": "Ignorer le mode lent",
    "connect": "Se connecter au vocal",
    "speak": "Parler",
    "stream": "Caméra / partage d'écran",
    "mute_members": "Couper le micro des membres",
    "deafen_members": "Mettre en sourdine les membres",
    "move_members": "Déplacer les membres",
    "use_voice_activation": "Détection de la voix",
    "priority_speaker": "Voix prioritaire",
    "request_to_speak": "Demander la parole",
    "use_soundboard": "Soundboard",
    "use_external_sounds": "Sons externes",
    "use_embedded_activities": "Activités",
}

# signalées d'un ⚠️ : ce sont celles qui permettent de prendre le contrôle du serveur
PERMS_SENSIBLES = {
    "administrator", "manage_guild", "manage_roles", "manage_channels", "ban_members",
    "kick_members", "moderate_members", "manage_webhooks", "mention_everyone",
    "manage_messages", "manage_nicknames", "mute_members", "deafen_members", "move_members",
}

TOUTES_PERMS = [nom for nom, _ in discord.Permissions.none()]


def nom_perm(perm: str) -> str:
    libelle = PERMS_FR.get(perm, perm.replace("_", " "))
    return f"⚠️ {libelle}" if perm in PERMS_SENSIBLES else libelle


def _etat(allow, deny, perm) -> str:
    if allow is not None and getattr(allow, perm, False):
        return "✅"
    if deny is not None and getattr(deny, perm, False):
        return "❌"
    return "⬜"


def diff_overwrite(avant_allow, avant_deny, apres_allow, apres_deny) -> list:
    """Lignes « Permission : ⬜ → ❌ » pour chaque permission qui a changé.
    ✅ autorisé · ❌ refusé · ⬜ hérité (ni l'un ni l'autre)."""
    lignes = []
    for perm in TOUTES_PERMS:
        a = _etat(avant_allow, avant_deny, perm)
        b = _etat(apres_allow, apres_deny, perm)
        if a != b:
            lignes.append(f"{nom_perm(perm)} : {a} → {b}")
    return lignes


def diff_permissions(avant, apres) -> tuple:
    """Permissions d'un rôle : (ajoutées, retirées)."""
    ajout, retrait = [], []
    for perm in TOUTES_PERMS:
        a = bool(avant and getattr(avant, perm, False))
        b = bool(apres and getattr(apres, perm, False))
        if b and not a:
            ajout.append(nom_perm(perm))
        elif a and not b:
            retrait.append(nom_perm(perm))
    return ajout, retrait


ATTRS = {
    "name": "Nom", "topic": "Sujet", "nsfw": "NSFW", "slowmode_delay": "Mode lent",
    "bitrate": "Débit audio", "user_limit": "Limite de membres", "rtc_region": "Région vocale",
    "video_quality_mode": "Qualité vidéo", "default_auto_archive_duration": "Archivage des fils",
    "category": "Catégorie", "colour": "Couleur", "color": "Couleur", "hoist": "Affiché séparément",
    "mentionable": "Mentionnable", "icon": "Icône", "unicode_emoji": "Emoji", "banner": "Bannière",
    "splash": "Image d'invitation", "description": "Description", "owner": "Propriétaire",
    "afk_channel": "Salon AFK", "afk_timeout": "Délai AFK", "system_channel": "Salon système",
    "rules_channel": "Salon des règles", "public_updates_channel": "Salon des annonces Discord",
    "verification_level": "Niveau de vérification", "explicit_content_filter": "Filtre de contenu",
    "default_notifications": "Notifications par défaut", "mfa_level": "2FA modération",
    "vanity_url_code": "URL personnalisée", "preferred_locale": "Langue",
    "code": "Code", "channel": "Salon", "inviter": "Créée par", "max_uses": "Utilisations max",
    "uses": "Utilisations", "max_age": "Expiration", "temporary": "Membre temporaire",
    "archived": "Archivé", "locked": "Verrouillé", "auto_archive_duration": "Archivage auto",
    "invitable": "Invitations", "emoji": "Emoji", "format_type": "Format", "tags": "Tags",
    "available": "Disponible", "privacy_level": "Confidentialité", "status": "Statut",
    "location": "Lieu", "start_time": "Début", "end_time": "Fin", "enabled": "Activé",
    "trigger": "Déclencheur", "actions": "Actions", "exempt_roles": "Rôles exemptés",
    "exempt_channels": "Salons exemptés", "volume": "Volume", "avatar": "Avatar",
}
# bruit ou traité à part
ATTRS_IGNORES = {"position", "overwrites", "permissions", "id", "type", "flags", "available_tags",
                 "default_reaction_emoji", "default_forum_layout", "default_sort_order",
                 "allow", "deny", "roles", "nick", "timed_out_until", "mute", "deaf",
                 "premium_progress_bar_enabled", "widget_enabled", "widget_channel"}


def _val(v, attr: str = "") -> str:
    if v is None or v is discord.utils.MISSING:
        return "—"
    if isinstance(v, bool):
        return "oui" if v else "non"
    if attr in ("slowmode_delay", "afk_timeout") and isinstance(v, int):
        return f"{v} s" if v else "désactivé"
    if attr == "max_age" and isinstance(v, int):
        return "jamais" if v == 0 else f"{v // 3600} h" if v >= 3600 else f"{v // 60} min"
    if attr == "max_uses" and isinstance(v, int):
        return "illimité" if v == 0 else str(v)
    if isinstance(v, discord.Colour):
        return str(v)
    if isinstance(v, datetime.datetime):
        return discord.utils.format_dt(v, "f")
    if isinstance(v, discord.Asset):
        return "(image)"
    if isinstance(v, discord.Object):
        return f"`{v.id}`"
    if hasattr(v, "mention"):
        return v.mention
    if isinstance(v, enum.Enum):
        return v.name
    if isinstance(v, (list, tuple, set)):
        return ", ".join(_val(x) for x in v) or "—"
    return _trim(str(v), 200)


def lignes_changements(entry) -> list:
    """« Nom : avant → après » pour chaque attribut modifié, en français."""
    avant, apres = entry.changes.before, entry.changes.after
    attrs = []
    for attr, _ in list(avant) + list(apres):
        if attr not in attrs and attr not in ATTRS_IGNORES:
            attrs.append(attr)
    lignes = []
    for attr in attrs:
        a, b = getattr(avant, attr, None), getattr(apres, attr, None)
        if a == b:
            continue
        lignes.append(f"**{ATTRS.get(attr, attr.replace('_', ' '))}** : {_val(a, attr)} → {_val(b, attr)}")
    return lignes


def _mention_id(obj, kind: str = "user") -> str:
    if obj is None:
        return "Inconnu"
    if not isinstance(obj, discord.Object) and hasattr(obj, "mention"):
        return obj.mention
    oid = getattr(obj, "id", obj)
    return {"user": f"<@{oid}>", "role": f"<@&{oid}>", "channel": f"<#{oid}>"}.get(kind, f"`{oid}`")


def deja_journalise(entry, bot_user) -> bool:
    """Sanctions passées par les commandes de Saphir : cogs/moderation.py et
    cogs/antiraid.py les journalisent déjà eux-mêmes, avec le vrai modérateur.
    On les reconnaît au format de raison qu'ils posent. Le honeypot, lui, ne
    journalise pas ses expulsions : elles passent ici."""
    if bot_user is None or entry.user_id != bot_user.id:
        return False
    raison = entry.reason or ""
    if entry.action in (A.kick, A.ban, A.unban):
        return " : " in raison or raison.startswith("Lockdown anti-raid")
    if entry.action is A.member_update and hasattr(entry.changes.after, "timed_out_until"):
        return " : " in raison or raison.startswith("Démute par")
    return False


# ──────────────────────────────── corrélation ─────────────────────────────────

class _Correlateur:
    """Retrouve l'auteur d'une action que l'événement Discord ne donne pas.

    Discord regroupe certaines entrées d'audit : deux messages de Y supprimés par X
    à quelques minutes d'écart ne font qu'UNE entrée, dont le compteur passe de 1
    à 2. Regarder « l'entrée la plus récente » attribuerait donc la seconde
    suppression à n'importe qui. On mémorise, pour chaque entrée, combien
    d'événements lui ont déjà été attribués : une entrée n'est candidate que si
    son compteur dépasse ce nombre.
    """

    FENETRE = 20          # s : une entrée découverte plus vieille que ça sert de référence
    ATTENTES = (1.5, 2.5)  # l'entrée d'audit arrive souvent après l'événement

    def __init__(self):
        self._attribues = {}   # (guild_id, action) -> {entry_id: nb d'événements attribués}
        self._verrous = {}

    @staticmethod
    def _compte(entry) -> int:
        return getattr(entry.extra, "count", None) or 1

    async def _passe(self, guild, action, accepte):
        cle = (guild.id, action)
        attribues = self._attribues.setdefault(cle, {})
        trouve = None
        maintenant = discord.utils.utcnow()
        async for e in guild.audit_logs(limit=15, action=action):
            n = self._compte(e)
            if e.id not in attribues:
                recent = (maintenant - e.created_at).total_seconds() <= self.FENETRE
                attribues[e.id] = 0 if recent else n
            if trouve is None and n > attribues[e.id] and accepte(e):
                attribues[e.id] += 1
                trouve = e
        if len(attribues) > 300:
            for vieux in sorted(attribues)[:-150]:
                attribues.pop(vieux, None)
        return trouve

    async def chercher(self, guild, action, accepte=lambda e: True):
        if not guild.me.guild_permissions.view_audit_log:
            return None
        verrou = self._verrous.setdefault((guild.id, action), asyncio.Lock())
        for attente in self.ATTENTES:
            await asyncio.sleep(attente)
            try:
                async with verrou:
                    e = await self._passe(guild, action, accepte)
            except discord.HTTPException:
                return None
            if e is not None:
                return e
        return None


# ──────────────────────────────────── cog ─────────────────────────────────────

class Logs(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        # cache mémoire {guild_id: {key: channel_id}} pour ne pas relire les réglages à chaque
        # évènement ; rempli à la demande, vidé par run_setup quand les salons changent
        self._log_ids = {}
        self._corr = _Correlateur()
        self.menage.start()

    async def cog_unload(self):
        self.menage.cancel()

    async def _channel_for(self, guild: discord.Guild, key: str):
        ids = self._log_ids.get(guild.id)
        if ids is None:
            settings = await aload_json(GUILD_SETTINGS_FILE, {})
            ids = settings.get(str(guild.id), {}).get("log_channel_ids", {})
            self._log_ids[guild.id] = ids
        channel = guild.get_channel(ids.get(key)) if ids.get(key) else None
        if channel is None:  # ID absent/périmé -> repli sur le nom (tolérant au style)
            channel = find_text_channel(guild, LOG_CHANNELS[key])
        if channel is None and key in REPLI:
            return await self._channel_for(guild, REPLI[key])
        return channel

    # ------------------------------------------------------------------ #
    #  Setup
    # ------------------------------------------------------------------ #

    @app_commands.command(
        name="setup-logs",
        description="Crée (ou met à jour) la catégorie de logs et tous ses salons, invisibles pour les membres",
    )
    @app_commands.checks.has_permissions(administrator=True)
    async def setup_logs(self, interaction: discord.Interaction):
        await interaction.response.defer(thinking=True, ephemeral=True)
        report = await run_setup(self.bot, interaction.guild)
        embed = discord.Embed(
            title="📋 Configuration des logs",
            description="\n".join(report),
            color=discord.Color(COLORS["saphir"]),
        )
        await interaction.followup.send(embed=embed, ephemeral=True)

    @setup_logs.error
    async def setup_logs_error(self, interaction: discord.Interaction, error: app_commands.AppCommandError):
        if isinstance(error, app_commands.MissingPermissions):
            await interaction.response.send_message("Seul un administrateur peut utiliser cette commande.", ephemeral=True)

    # ------------------------------------------------------------------ #
    #  Envoi
    # ------------------------------------------------------------------ #

    @staticmethod
    def _construire(pieces) -> list:
        """discord.File à partir de (chemin ou octets, nom). Reconstruits à chaque
        envoi : discord.py ferme les fichiers après une requête, même ratée."""
        return [discord.File(io.BytesIO(src) if isinstance(src, bytes) else src, filename=nom)
                for src, nom in pieces]

    async def _log(self, guild: discord.Guild, key: str, embed: discord.Embed, pieces=None):
        """`pieces` : liste de (chemin ou octets, nom de fichier) à joindre."""
        channel = await self._channel_for(guild, key)
        if not channel:
            return
        if embed.timestamp is None:
            embed.timestamp = discord.utils.utcnow()
        try:
            await channel.send(embed=embed, files=self._construire(pieces or []))
        except discord.HTTPException:
            if not pieces:
                return
            # souvent trop lourd pour un seul message : l'embed seul, puis un fichier par message
            try:
                await channel.send(embed=embed)
            except discord.HTTPException:
                return
            for piece in pieces:
                try:
                    await channel.send(files=self._construire([piece]))
                except discord.HTTPException:
                    pass

    def _par(self, entry) -> str:
        """« Par » d'une entrée d'audit. Quand c'est Saphir qui a agi, la raison
        (affichée à côté) nomme le membre qui a lancé la commande."""
        if entry.user_id is None:
            return "Inconnu"
        if self.bot.user and entry.user_id == self.bot.user.id:
            return f"🤖 <@{entry.user_id}> (Saphir" + (", voir la raison)" if entry.reason else ")")
        membre = entry.guild.get_member(entry.user_id) if entry.guild else None
        return f"<@{entry.user_id}>" + (f" · `{membre}`" if membre else "")

    def _embed(self, titre: str, couleur: str, entry=None, *, cible: str = None, texte: str = None):
        lignes = []
        if cible:
            lignes.append(f"**Cible** : {cible}")
        if entry is not None:
            lignes.append(f"**Par** : {self._par(entry)}")
        if texte:
            lignes.append(texte)
        embed = discord.Embed(title=titre, description="\n".join(lignes), color=discord.Color(COLORS[couleur]))
        if entry is not None:
            embed.timestamp = entry.created_at
            if entry.reason:
                embed.add_field(name="Raison", value=_trim(entry.reason, 1000), inline=False)
            cid = getattr(entry.target, "id", None)
            embed.set_footer(text=f"Auteur ID : {entry.user_id}" + (f" · Cible ID : {cid}" if cid else ""))
        return embed

    # ------------------------------------------------------------------ #
    #  1. Journal d'audit, en temps réel
    # ------------------------------------------------------------------ #

    # Attribués par corrélation dans les listeners dédiés, pour y joindre le contenu
    # du message ou le salon vocal : les journaliser ici ferait doublon.
    _PAR_CORRELATION = {A.message_delete, A.message_bulk_delete, A.member_move, A.member_disconnect}

    @commands.Cog.listener()
    async def on_audit_log_entry_create(self, entry: discord.AuditLogEntry):
        if entry.action in self._PAR_CORRELATION or deja_journalise(entry, self.bot.user):
            return
        try:
            for key, embed in self._depuis_audit(entry):
                await self._log(entry.guild, key, embed)
        except Exception as e:  # un log raté ne doit jamais faire tomber le listener
            print(f"[logs] entrée d'audit {entry.action.name} non journalisée : {type(e).__name__} : {e}")

    def _depuis_audit(self, entry) -> list:
        act, av, ap = entry.action, entry.changes.before, entry.changes.after
        cible_membre = _mention_id(entry.target, "user")
        out = []

        # ── membres : sanctions ──
        if act is A.kick:
            out.append(("moderation", self._embed("🥾 Expulsion", "danger", entry, cible=cible_membre)))
        elif act is A.ban:
            out.append(("moderation", self._embed("🔨 Bannissement", "danger", entry, cible=cible_membre)))
        elif act is A.unban:
            out.append(("moderation", self._embed("🔓 Débannissement", "success", entry, cible=cible_membre)))
        elif act is A.member_prune:
            ex = entry.extra
            out.append(("moderation", self._embed(
                "🧹 Purge de membres inactifs", "danger", entry,
                texte=f"**Membres retirés** : {getattr(ex, 'members_removed', '?')}\n"
                      f"**Inactifs depuis** : {getattr(ex, 'delete_member_days', '?')} jours")))

        # ── membres : pseudo, timeout, micro / sourdine imposés par le serveur ──
        elif act is A.member_update:
            soi = entry.user_id == getattr(entry.target, "id", None)
            if hasattr(ap, "nick") or hasattr(av, "nick"):
                e = self._embed("✏️ Pseudo modifié" + (" (par lui-même)" if soi else ""), "gold",
                                entry, cible=cible_membre)
                e.add_field(name="Avant", value=_trim(getattr(av, "nick", None) or "*(aucun)*", 200))
                e.add_field(name="Après", value=_trim(getattr(ap, "nick", None) or "*(aucun)*", 200))
                out.append(("profile", e))
            if hasattr(ap, "timed_out_until") or hasattr(av, "timed_out_until"):
                fin = getattr(ap, "timed_out_until", None)
                if fin and fin > discord.utils.utcnow():
                    duree = fin - entry.created_at
                    e = self._embed("🔇 Timeout", "danger", entry, cible=cible_membre)
                    e.add_field(name="Jusqu'à", value=discord.utils.format_dt(fin, "F"))
                    e.add_field(name="Durée", value=_duree(duree))
                else:
                    e = self._embed("🔊 Timeout retiré", "success", entry, cible=cible_membre)
                out.append(("moderation", e))
            for attr, coupe, retabli in (
                ("mute", "🔇 Micro coupé par le serveur", "🎤 Micro rétabli par le serveur"),
                ("deaf", "🙉 Mis en sourdine par le serveur", "👂 Sourdine serveur retirée"),
            ):
                if hasattr(ap, attr):
                    actif = bool(getattr(ap, attr))
                    out.append(("voice", self._embed(coupe if actif else retabli,
                                                     "danger" if actif else "success",
                                                     entry, cible=cible_membre)))

        elif act is A.member_role_update:
            ajoutes = getattr(ap, "roles", None) or []
            retires = getattr(av, "roles", None) or []
            e = self._embed("🎭 Rôles modifiés", "gold", entry, cible=cible_membre)
            if ajoutes:
                e.add_field(name="➕ Donné(s)", value=", ".join(_mention_id(r, "role") for r in ajoutes), inline=False)
            if retires:
                e.add_field(name="➖ Retiré(s)", value=", ".join(_mention_id(r, "role") for r in retires), inline=False)
            out.append(("roles", e))

        # ── permissions des salons ──
        elif act in (A.overwrite_create, A.overwrite_update, A.overwrite_delete):
            qui = entry.extra
            if isinstance(qui, discord.Role) or getattr(qui, "type", None) == discord.Role:
                pour = _mention_id(qui, "role")
            else:
                pour = _mention_id(qui, "user")
            titre = {A.overwrite_create: "🔐 Permissions ajoutées sur un salon",
                     A.overwrite_update: "🔐 Permissions modifiées sur un salon",
                     A.overwrite_delete: "🔐 Permissions retirées d'un salon"}[act]
            e = self._embed(titre, "gold", entry, cible=_mention_id(entry.target, "channel"),
                            texte=f"**Pour** : {pour}")
            lignes = diff_overwrite(getattr(av, "allow", None), getattr(av, "deny", None),
                                    getattr(ap, "allow", None), getattr(ap, "deny", None))
            e.add_field(name="Changements  (✅ autorisé · ❌ refusé · ⬜ hérité)",
                        value=_trim("\n".join(lignes) or "aucun changement effectif", 1024), inline=False)
            out.append(("permissions", e))

        # ── rôles ──
        elif act in (A.role_create, A.role_delete, A.role_update):
            nom = getattr(ap, "name", None) or getattr(av, "name", None)
            cible = _mention_id(entry.target, "role") if act is not A.role_delete else f"**{nom or '?'}**"
            titre = {A.role_create: "🎭 Rôle créé", A.role_delete: "🎭 Rôle supprimé",
                     A.role_update: "🎭 Rôle modifié"}[act]
            couleur = {A.role_create: "success", A.role_delete: "danger", A.role_update: "gold"}[act]
            lignes = lignes_changements(entry)
            if lignes or act is not A.role_update:
                e = self._embed(titre, couleur, entry, cible=cible)
                if lignes:
                    e.add_field(name="Détails", value=_trim("\n".join(lignes), 1024), inline=False)
                out.append(("roles", e))
            if hasattr(ap, "permissions") or hasattr(av, "permissions"):
                ajout, retrait = diff_permissions(getattr(av, "permissions", None), getattr(ap, "permissions", None))
                if ajout or retrait:
                    e = self._embed("🔐 Permissions d'un rôle modifiées", "gold", entry, cible=cible)
                    if ajout:
                        e.add_field(name="➕ Accordées", value=_trim("\n".join(ajout), 1024), inline=False)
                    if retrait:
                        e.add_field(name="➖ Retirées", value=_trim("\n".join(retrait), 1024), inline=False)
                    out.append(("permissions", e))

        # ── salons et fils ──
        elif act in (A.channel_create, A.channel_delete, A.channel_update,
                     A.thread_create, A.thread_delete, A.thread_update):
            nom = getattr(ap, "name", None) or getattr(av, "name", None)
            supprime = act in (A.channel_delete, A.thread_delete)
            cible = f"**{nom or '?'}**" if supprime else _mention_id(entry.target, "channel")
            fil = act in (A.thread_create, A.thread_delete, A.thread_update)
            quoi = "Fil" if fil else "Salon"
            titre = {A.channel_create: "créé", A.thread_create: "créé", A.channel_delete: "supprimé",
                     A.thread_delete: "supprimé", A.channel_update: "modifié", A.thread_update: "modifié"}[act]
            couleur = "danger" if supprime else "success" if titre == "créé" else "gold"
            lignes = lignes_changements(entry)
            if lignes or titre != "modifié":
                e = self._embed(f"📁 {quoi} {titre}", couleur, entry, cible=cible)
                if lignes:
                    e.add_field(name="Détails", value=_trim("\n".join(lignes), 1024), inline=False)
                out.append(("channels", e))

        # ── messages épinglés ──
        elif act in (A.message_pin, A.message_unpin):
            ex = entry.extra
            salon = getattr(ex, "channel", None)
            mid = getattr(ex, "message_id", None)
            lien = (f"https://discord.com/channels/{entry.guild.id}/{salon.id}/{mid}"
                    if salon is not None and mid else None)
            e = self._embed("📌 Message épinglé" if act is A.message_pin else "📌 Message désépinglé",
                            "gold", entry, cible=f"message de {cible_membre}",
                            texte=f"**Salon** : {_mention_id(salon, 'channel')}" + (f" · [Voir]({lien})" if lien else ""))
            out.append(("messages", e))

        # ── automod ──
        elif act in (A.automod_block_message, A.automod_flag_message,
                     A.automod_timeout_member, A.automod_quarantine_user):
            ex = entry.extra
            libelle = {A.automod_block_message: "🛡️ AutoMod : message bloqué",
                       A.automod_flag_message: "🛡️ AutoMod : message signalé",
                       A.automod_timeout_member: "🛡️ AutoMod : timeout",
                       A.automod_quarantine_user: "🛡️ AutoMod : membre mis en quarantaine"}[act]
            e = self._embed(libelle, "danger", None, cible=cible_membre,
                            texte=f"**Règle** : {getattr(ex, 'automod_rule_name', '?')}\n"
                                  f"**Salon** : {_mention_id(getattr(ex, 'channel', None), 'channel')}")
            e.timestamp = entry.created_at
            out.append(("moderation", e))

        # ── sécurité du serveur : bots, webhooks, intégrations ──
        elif act is A.bot_add:
            out.append(("server", self._embed("⚠️ Bot ajouté au serveur", "danger", entry, cible=cible_membre)))
        elif act in (A.webhook_create, A.webhook_update, A.webhook_delete,
                     A.integration_create, A.integration_update, A.integration_delete):
            quoi = "Webhook" if act.name.startswith("webhook") else "Intégration"
            fait = act.name.split("_")[1]
            titre = f"🔗 {quoi} " + {"create": "créé(e)", "update": "modifié(e)", "delete": "supprimé(e)"}[fait]
            e = self._embed(titre, "danger" if fait != "update" else "gold", entry)
            lignes = lignes_changements(entry)
            if lignes:
                e.add_field(name="Détails", value=_trim("\n".join(lignes), 1024), inline=False)
            out.append(("server", e))

        # ── invitations ──
        elif act in (A.invite_create, A.invite_update, A.invite_delete):
            titre = {A.invite_create: "✉️ Invitation créée", A.invite_update: "✉️ Invitation modifiée",
                     A.invite_delete: "✉️ Invitation supprimée"}[act]
            e = self._embed(titre, "grey", entry)
            lignes = lignes_changements(entry)
            if lignes:
                e.add_field(name="Détails", value=_trim("\n".join(lignes), 1024), inline=False)
            out.append(("server", e))

        # ── tout le reste : serveur, emojis, autocollants, événements, AutoMod... ──
        else:
            lignes = lignes_changements(entry)
            titre = "⚙️ " + {
                A.guild_update: "Serveur modifié",
            }.get(act, act.name.replace("_", " ").capitalize())
            e = self._embed(titre, "gold", entry)
            if lignes:
                e.add_field(name="Détails", value=_trim("\n".join(lignes), 1024), inline=False)
            if lignes or act is not A.guild_update:
                out.append(("server", e))
        return out

    # ------------------------------------------------------------------ #
    #  2. Arrivées / départs / profil
    # ------------------------------------------------------------------ #

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        age = discord.utils.utcnow() - member.created_at
        embed = discord.Embed(
            title="📥 Arrivée",
            description=f"{member.mention} ({member})",
            color=discord.Color(COLORS["success"]),
        )
        embed.add_field(name="Compte créé", value=f"{discord.utils.format_dt(member.created_at, style='R')}")
        if age.days < 7:
            embed.add_field(name="⚠️", value="Compte créé il y a moins de 7 jours")
        if member.bot:
            embed.add_field(name="🤖", value="C'est un bot")
        embed.set_thumbnail(url=member.display_avatar.url)
        embed.set_footer(text=f"ID : {member.id}")
        await self._log(member.guild, "join_leave", embed)

    @commands.Cog.listener()
    async def on_member_remove(self, member: discord.Member):
        guild = member.guild
        roles = [r.mention for r in member.roles if not r.is_default()]
        embed = discord.Embed(
            title="📤 Départ",
            description=f"{member.mention} ({member})",
            color=discord.Color(COLORS["grey"]),
        )
        embed.add_field(name="Arrivé", value=discord.utils.format_dt(member.joined_at, style="R") if member.joined_at else "Inconnu")
        embed.add_field(name="Rôles qu'il avait", value=_trim(", ".join(roles), 1024) if roles else "Aucun", inline=False)
        embed.set_footer(text=f"ID : {member.id}")
        # parti de lui-même, ou mis dehors ? (le détail de la sanction est dans #modération)
        for action, libelle in ((A.kick, "🥾 Expulsé"), (A.ban, "🔨 Banni")):
            entry = await self._corr.chercher(guild, action, lambda e: getattr(e.target, "id", None) == member.id)
            if entry:
                embed.title = f"📤 Départ — {libelle.split(' ', 1)[1].lower()}"
                embed.add_field(name=libelle + " par", value=self._par(entry), inline=False)
                break
        await self._log(guild, "join_leave", embed)

    @commands.Cog.listener()
    async def on_member_update(self, before: discord.Member, after: discord.Member):
        # pseudo, rôles et timeout passent par le journal d'audit (avec leur auteur) ;
        # ici seulement ce qu'il ignore : les boosts
        if before.premium_since is None and after.premium_since is not None:
            embed = discord.Embed(title="🚀 Nouveau boost", description=f"{after.mention} a boosté le serveur",
                                  color=discord.Color(COLORS["saphir"]))
            embed.set_footer(text=f"ID : {after.id}")
            await self._log(after.guild, "server", embed)
        elif before.premium_since is not None and after.premium_since is None:
            embed = discord.Embed(title="🚀 Boost retiré", description=f"{after.mention} ne booste plus le serveur",
                                  color=discord.Color(COLORS["grey"]))
            embed.set_footer(text=f"ID : {after.id}")
            await self._log(after.guild, "server", embed)

    @commands.Cog.listener()
    async def on_user_update(self, before: discord.User, after: discord.User):
        changements = []
        if before.name != after.name:
            changements.append(("🏷️ Nom d'utilisateur modifié", before.name, after.name))
        if before.global_name != after.global_name:
            changements.append(("🏷️ Nom affiché modifié", before.global_name or "*(aucun)*", after.global_name or "*(aucun)*"))
        avatar = before.display_avatar.key != after.display_avatar.key
        if not changements and not avatar:
            return

        for guild in self.bot.guilds:
            member = guild.get_member(after.id)
            if member is None:
                continue
            for titre, avant, apres in changements:
                embed = discord.Embed(title=titre, description=member.mention, color=discord.Color(COLORS["gold"]))
                embed.add_field(name="Avant", value=_trim(avant, 200))
                embed.add_field(name="Après", value=_trim(apres, 200))
                embed.set_footer(text=f"ID : {after.id}")
                await self._log(guild, "profile", embed)
            if avatar:
                embed = discord.Embed(title="🖼️ Avatar modifié", description=member.mention, color=discord.Color(COLORS["gold"]))
                embed.set_thumbnail(url=before.display_avatar.url)
                embed.set_image(url=after.display_avatar.url)
                embed.add_field(name="Ancien", value="en petit, à droite")
                embed.add_field(name="Nouveau", value="en grand, en dessous")
                embed.set_footer(text=f"ID : {after.id}")
                await self._log(guild, "profile", embed)

    # ------------------------------------------------------------------ #
    #  3. Messages : contenu, images, et qui les supprime
    # ------------------------------------------------------------------ #

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.guild is None or message.author.bot:
            return
        try:
            await message_store.enregistrer(message)
        except Exception as e:
            print(f"[logs] message {message.id} non mémorisé : {e}")

    @staticmethod
    def _fichiers(message_id: int, pjs: list) -> tuple:
        """Copies locales des pièces jointes, prêtes à renvoyer (chemin, nom), et la
        liste texte de celles qu'on n'a pas pu garder."""
        pieces, perdues = [], []
        for i, pj in enumerate(pjs):
            chemin = message_store.chemin_fichier(message_id, pj)
            if chemin and len(pieces) < 10:
                # nom sans caractères spéciaux : c'est lui qu'on cite dans attachment://
                pieces.append((chemin, f"{i}_{re.sub(r'[^A-Za-z0-9._-]', '_', pj['filename'])}"))
            else:
                perdues.append(f"`{pj['filename']}` ({_taille(pj.get('size'))})")
        return pieces, perdues

    @staticmethod
    def _premiere_image(pieces: list):
        for _src, nom in pieces:
            if nom.lower().endswith((".png", ".jpg", ".jpeg", ".gif", ".webp")):
                return nom
        return None

    @commands.Cog.listener()
    async def on_raw_message_delete(self, payload: discord.RawMessageDeleteEvent):
        if payload.guild_id is None:
            return
        guild = self.bot.get_guild(payload.guild_id)
        if guild is None:
            return
        cache = payload.cached_message
        if cache is not None and cache.author.bot:
            return
        garde = await message_store.lire(payload.message_id)

        if garde is not None:
            auteur_id, contenu, pjs = garde["author_id"], garde["content"], garde["attachments"]
            envoye, reponse = garde["created_at"], garde["reply_to"]
            auteur_tag = garde["author_tag"]
        elif cache is not None:
            auteur_id, contenu = cache.author.id, cache.content
            pjs = [{"id": a.id, "filename": a.filename, "size": a.size, "local": False} for a in cache.attachments]
            envoye, reponse = cache.created_at.timestamp(), (cache.reference.message_id if cache.reference else None)
            auteur_tag = str(cache.author)
        else:
            auteur_id = None

        # Une suppression par l'auteur lui-même ne laisse aucune trace d'audit :
        # pas d'entrée trouvée = c'est lui. Sinon l'entrée nomme le modérateur.
        def accepte(e):
            salon = getattr(e.extra, "channel", None)
            if salon is None or salon.id != payload.channel_id:
                return False
            return auteur_id is None or getattr(e.target, "id", None) == auteur_id
        entry = await self._corr.chercher(guild, A.message_delete, accepte)

        if auteur_id is None:
            # message ni en mémoire ni en cache (antérieur, ou d'un bot) : on ne le
            # signale que si quelqu'un d'autre l'a supprimé
            if entry is None:
                return
            embed = discord.Embed(
                title="🗑️ Message supprimé par un modérateur",
                description=(f"**Salon** : <#{payload.channel_id}>\n"
                             f"**Auteur du message** : {_mention_id(entry.target, 'user')}\n"
                             f"**Supprimé par** : {self._par(entry)}\n"
                             "*Contenu inconnu : message antérieur à la mémoire des logs.*"),
                color=discord.Color(COLORS["danger"]),
            )
            embed.set_footer(text=f"ID message : {payload.message_id}")
            await self._log(guild, "messages", embed)
            return

        par = f"{self._par(entry)}" if entry else f"<@{auteur_id}> lui-même"
        lignes = [
            f"**Auteur** : <@{auteur_id}> · `{auteur_tag}`",
            f"**Salon** : <#{payload.channel_id}>",
            f"**Envoyé** : <t:{int(envoye)}:f> (<t:{int(envoye)}:R>)",
            f"**Supprimé par** : {par}",
        ]
        if reponse:
            lignes.append(f"**En réponse à** : https://discord.com/channels/{guild.id}/{payload.channel_id}/{reponse}")
        lignes.append("")
        lignes.append("**Contenu**")
        lignes.append(_trim(contenu, 3000))
        embed = discord.Embed(
            title="🗑️ Message supprimé" + (" par un modérateur" if entry else ""),
            description="\n".join(lignes),
            color=discord.Color(COLORS["danger"]),
        )
        fichiers, perdues = self._fichiers(payload.message_id, pjs)
        if fichiers:
            embed.add_field(name=f"📎 Pièces jointes récupérées ({len(fichiers)})",
                            value="Renvoyées avec ce message", inline=False)
            image = self._premiere_image(fichiers)
            if image:
                embed.set_image(url=f"attachment://{image}")
        if perdues:
            embed.add_field(name="📎 Pièces jointes non récupérables",
                            value=_trim("\n".join(perdues), 1024) + "\n-# trop lourdes, ou supprimées avant d'avoir pu être copiées",
                            inline=False)
        if entry and entry.reason:
            embed.add_field(name="Raison", value=_trim(entry.reason, 1000), inline=False)
        embed.set_footer(text=f"ID auteur : {auteur_id} · ID message : {payload.message_id}")
        await self._log(guild, "messages", embed, pieces=fichiers)
        await message_store.oublier(payload.message_id)

    @commands.Cog.listener()
    async def on_raw_bulk_message_delete(self, payload: discord.RawBulkMessageDeleteEvent):
        if payload.guild_id is None:
            return
        guild = self.bot.get_guild(payload.guild_id)
        if guild is None:
            return
        gardes = await message_store.lire_plusieurs(payload.message_ids)
        for m in payload.cached_messages:
            if m.id not in gardes and not m.author.bot:
                gardes[m.id] = {"author_id": m.author.id, "author_tag": str(m.author), "content": m.content,
                                "attachments": [{"filename": a.filename} for a in m.attachments],
                                "created_at": m.created_at.timestamp()}
        entry = await self._corr.chercher(
            guild, A.message_bulk_delete, lambda e: getattr(e.target, "id", None) == payload.channel_id
        )

        lignes = []
        for mid, g in sorted(gardes.items(), key=lambda kv: kv[1]["created_at"]):
            date = datetime.datetime.fromtimestamp(g["created_at"], tz=datetime.timezone.utc)
            pj = ", ".join(p["filename"] for p in g.get("attachments") or [])
            lignes.append(f"[{date:%d/%m/%Y %H:%M:%S} UTC] {g['author_tag']} ({g['author_id']}) : "
                          f"{g['content'] or ''}" + (f"  [pièces jointes : {pj}]" if pj else ""))
        total, connus = len(payload.message_ids), len(gardes)
        embed = discord.Embed(
            title="🧹 Suppression en masse",
            description=(f"**Salon** : <#{payload.channel_id}>\n"
                         f"**Messages supprimés** : {total} (contenu connu : {connus})\n"
                         f"**Par** : {self._par(entry) if entry else 'inconnu (bot ou commande)'}"),
            color=discord.Color(COLORS["danger"]),
        )
        if entry and entry.reason:
            embed.add_field(name="Raison", value=_trim(entry.reason, 1000), inline=False)
        fichiers = []
        if lignes:
            texte = "\n".join(lignes).encode("utf-8")
            fichiers.append((texte, f"suppression-{payload.channel_id}.txt"))
            embed.add_field(name="Contenu", value="Dans le fichier joint", inline=False)
        await self._log(guild, "messages", embed, pieces=fichiers)
        for mid in payload.message_ids:
            await message_store.oublier(mid)

    @commands.Cog.listener()
    async def on_raw_message_edit(self, payload: discord.RawMessageUpdateEvent):
        if payload.guild_id is None:
            return
        data = payload.data
        if (data.get("author") or {}).get("bot"):
            return
        # Discord renvoie aussi le message quand il ajoute un aperçu de lien : seule une
        # vraie édition porte un edited_timestamp
        if not data.get("edited_timestamp"):
            return
        guild = self.bot.get_guild(payload.guild_id)
        if guild is None:
            return

        garde = await message_store.lire(payload.message_id)
        cache = payload.cached_message
        avant = garde["content"] if garde else (cache.content if cache else None)
        pjs_avant = garde["attachments"] if garde else []
        apres = data.get("content", avant)
        ids_apres = {int(a["id"]) for a in data.get("attachments") or []}
        retirees = [p for p in pjs_avant if p.get("id") and int(p["id"]) not in ids_apres] \
            if "attachments" in data else []
        if avant == apres and not retirees:
            return

        auteur = data.get("author") or {}
        auteur_id = auteur.get("id") or (garde["author_id"] if garde else "?")
        lien = f"https://discord.com/channels/{guild.id}/{payload.channel_id}/{payload.message_id}"
        lignes = [f"**Auteur** : <@{auteur_id}>",
                  f"**Salon** : <#{payload.channel_id}> · [Aller au message]({lien})", ""]
        if avant != apres:
            lignes += ["**Avant**", _trim(avant if avant is not None else "*(version précédente inconnue)*", 1800),
                       "", "**Après**", _trim(apres, 1800)]
        embed = discord.Embed(title="✏️ Message modifié", description="\n".join(lignes),
                              color=discord.Color(COLORS["gold"]))
        fichiers = []
        if retirees:
            fichiers, perdues = self._fichiers(payload.message_id, retirees)
            noms = ", ".join(f"`{p['filename']}`" for p in retirees)
            embed.add_field(name="📎 Pièce(s) jointe(s) retirée(s) du message", value=_trim(noms, 1024), inline=False)
            image = self._premiere_image(fichiers)
            if image:
                embed.set_image(url=f"attachment://{image}")
        embed.set_footer(text=f"ID auteur : {auteur_id} · ID message : {payload.message_id}")
        await self._log(guild, "messages", embed, pieces=fichiers)

        if garde is not None:
            restantes = [p for p in pjs_avant if p not in retirees] if retirees else None
            await message_store.modifier(payload.message_id, apres or "", restantes)

    # ------------------------------------------------------------------ #
    #  4. Vocal : qui a rejoint, qui a été déplacé ou déconnecté, et par qui
    # ------------------------------------------------------------------ #

    @commands.Cog.listener()
    async def on_voice_state_update(
        self, member: discord.Member, before: discord.VoiceState, after: discord.VoiceState
    ):
        guild = member.guild

        if before.channel != after.channel:
            if before.channel is None:
                embed = discord.Embed(
                    title="🎙️ Connexion vocale",
                    description=f"{member.mention} a rejoint {after.channel.mention}",
                    color=discord.Color(COLORS["success"]),
                )
            elif after.channel is None:
                entry = await self._corr.chercher(guild, A.member_disconnect)
                if entry:
                    embed = discord.Embed(
                        title="⛔ Déconnecté du vocal",
                        description=f"{member.mention} a été déconnecté de {before.channel.mention}\n"
                                    f"**Par** : {self._par(entry)}",
                        color=discord.Color(COLORS["danger"]),
                    )
                    if entry.reason:
                        embed.add_field(name="Raison", value=_trim(entry.reason, 1000), inline=False)
                else:
                    embed = discord.Embed(
                        title="🎙️ Déconnexion vocale",
                        description=f"{member.mention} a quitté {before.channel.mention}",
                        color=discord.Color(COLORS["grey"]),
                    )
            else:
                entry = await self._corr.chercher(
                    guild, A.member_move,
                    lambda e: getattr(getattr(e.extra, "channel", None), "id", None) == after.channel.id,
                )
                if entry:
                    embed = discord.Embed(
                        title="🔀 Déplacé de salon vocal",
                        description=f"{member.mention} : {before.channel.mention} → {after.channel.mention}\n"
                                    f"**Par** : {self._par(entry)}",
                        color=discord.Color(COLORS["gold"]),
                    )
                    if entry.reason:
                        embed.add_field(name="Raison", value=_trim(entry.reason, 1000), inline=False)
                else:
                    embed = discord.Embed(
                        title="🎙️ Changement de salon vocal",
                        description=f"{member.mention} : {before.channel.mention} → {after.channel.mention} (de lui-même)",
                        color=discord.Color(COLORS["gold"]),
                    )
            embed.set_footer(text=f"ID : {member.id}")
            await self._log(guild, "voice", embed)

        # Ce qu'un membre fait sur lui-même, depuis son application. Le micro coupé ou la
        # sourdine imposés par un modérateur arrivent, eux, par le journal d'audit avec
        # leur auteur (voir member_update dans _depuis_audit).
        toggles = [
            ("self_mute", "🎤 a coupé son propre micro", "🎤 a réactivé son micro"),
            ("self_deaf", "🔇 s'est mis en sourdine (n'entend plus)", "🔇 a retiré sa sourdine"),
            ("self_stream", "🖥️ a commencé un partage d'écran", "🖥️ a arrêté son partage d'écran"),
            ("self_video", "🎥 a activé sa caméra", "🎥 a désactivé sa caméra"),
        ]
        salon = after.channel or before.channel
        for attr, on_text, off_text in toggles:
            before_val = getattr(before, attr)
            after_val = getattr(after, attr)
            if before_val == after_val:
                continue
            embed = discord.Embed(
                title="🎙️ Vocal (action perso)",
                description=f"{member.mention} {on_text if after_val else off_text}"
                            + (f" dans {salon.mention}" if salon else ""),
                color=discord.Color(COLORS["grey"]),
            )
            embed.set_footer(text=f"ID : {member.id}")
            await self._log(guild, "voice", embed)

    # ------------------------------------------------------------------ #
    #  Démarrage et ménage
    # ------------------------------------------------------------------ #

    @commands.Cog.listener()
    async def on_ready(self):
        for guild in self.bot.guilds:
            if guild.me.guild_permissions.view_audit_log:
                continue
            print(f"⚠️ [logs] {guild.name} : pas de permission « Voir les logs du serveur », auteurs invisibles")
            embed = discord.Embed(
                title="⚠️ Logs incomplets",
                description="Saphir n'a pas la permission **Voir les logs du serveur**.\n"
                            "Sans elle, impossible de savoir **qui** donne un rôle, met un timeout, coupe un "
                            "micro, déplace quelqu'un ou touche aux permissions.\n"
                            "→ Paramètres du serveur → Rôles → rôle de Saphir → active-la.",
                color=discord.Color(COLORS["danger"]),
            )
            await self._log(guild, "server", embed)

    @tasks.loop(hours=1)
    async def menage(self):
        try:
            await message_store.purger()
        except Exception as e:
            print(f"[logs] ménage de la mémoire des messages : {e}")

    @menage.before_loop
    async def _avant_menage(self):
        await self.bot.wait_until_ready()


def _duree(delta: datetime.timedelta) -> str:
    s = int(delta.total_seconds())
    if s < 0:
        return "—"
    j, s = divmod(s, 86400)
    h, s = divmod(s, 3600)
    m, s = divmod(s, 60)
    morceaux = [f"{j} j" if j else "", f"{h} h" if h else "", f"{m} min" if m else ""]
    return " ".join(x for x in morceaux if x) or f"{s} s"


def _taille(octets) -> str:
    if not octets:
        return "?"
    for unite in ("o", "Ko", "Mo", "Go"):
        if octets < 1024:
            return f"{octets:.0f} {unite}"
        octets /= 1024
    return f"{octets:.1f} To"


async def setup(bot):
    await bot.add_cog(Logs(bot))
