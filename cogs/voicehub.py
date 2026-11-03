import os
import random
import time

import discord
from discord import app_commands
from discord.ext import commands, tasks

from cogs._shared import handle_app_error
from storage import aload_json, asave_json
from services.setup_kit import (
    adopt_category,
    adopt_text_channel,
    adopt_voice_channel,
    ensure_role,
    post_once,
    readonly_overwrites,
)
from config import (
    COLORS,
    GUILD_SETTINGS_FILE,
    VOICE_HUB_CATEGORY_NAME,
    VOICE_HUB_CHANNEL_NAME,
    VOICE_HUB_INFO_CHANNEL_NAME,
    VOICE_ROLE_NAME,
)

# anti-spam : délai minimal entre deux créations de salon perso par le même membre
SPAWN_COOLDOWN_SECONDS = 15

# prefixe des salons perso crees par le hub -- sert de repli pour les reconnaitre et les
# supprimer meme apres un redemarrage du bot (le suivi par ID en memoire est alors perdu)
TEMP_CHANNEL_PREFIX = "🔊 Salon de "

CONTROL_PANEL_TEXT = (
    "✏️ **Renommer** · 🔢 **Limite** · 🔒 **Verrouiller** · 👁️ **Masquer**\n"
    "🤝 **Inviter** · 🔇 **Muet** · ⛔ **Exclure** · ↩️ **Réintégrer**\n"
    "👑 **Transférer** le salon · 🙋 **Réclamer** un salon abandonné"
)

BANNIERES_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "assets", "vocal")
COULEUR_PANNEAU = 0xCBA6F7      # Catppuccin « Mauve », comme les rôles du serveur


async def run_setup(bot, guild: discord.Guild) -> list:
    """Logique de /setup-vocal, appelable aussi par /setup-tout."""
    report = []

    # role donne pendant qu'un membre est en vocal (cogs/voicerole.py) : personne ne le
    # creait jusqu'ici, donc la feature ne faisait rien du tout
    _role, line = await ensure_role(guild, VOICE_ROLE_NAME)
    report.append(line)

    category, line = await adopt_category(guild, VOICE_HUB_CATEGORY_NAME, keywords=["vocal", "vocaux", "appel", "voice"])
    report.append(line)
    if category is None:
        return report

    # si un hub a deja ete defini (par un setup precedent ou via /definir-hub-vocal) et qu'il
    # existe toujours, on le REUTILISE au lieu d'en recreer un -- sinon chaque /setup-vocal
    # fabriquait un doublon quand le salon avait ete renomme/deplace hors du nom exact
    settings = await aload_json(GUILD_SETTINGS_FILE, {})
    guild_settings = settings.setdefault(str(guild.id), {})
    existing_hub_id = guild_settings.get("voice_hub_channel_id")
    hub = guild.get_channel(existing_hub_id) if existing_hub_id else None
    if isinstance(hub, discord.VoiceChannel):
        report.append(f"= Hub vocal déjà défini : {hub.name}")
    else:
        hub, line = await adopt_voice_channel(
            guild, VOICE_HUB_CHANNEL_NAME, category=category,
            keywords=["creer-un-salon", "creer-ton-salon", "creerunsalon"],
        )
        report.append(line)

    # on memorise l'ID du hub : le listener le repere par ID, pas par nom, pour survivre
    # a un renommage (renommer le salon cassait silencieusement la creation de salons)
    if isinstance(hub, discord.VoiceChannel):
        guild_settings["voice_hub_channel_id"] = hub.id
        await asave_json(GUILD_SETTINGS_FILE, settings)

    info_channel, line = await adopt_text_channel(
        guild, VOICE_HUB_INFO_CHANNEL_NAME, category=category,
        keywords=["infos-vocal", "infos-vocaux"], overwrites=readonly_overwrites(guild)
    )
    report.append(line)

    info_text = (
        "🎧 **Salons vocaux personnels**\n\n"
        f"Rejoins **{VOICE_HUB_CHANNEL_NAME}** pour obtenir aussitôt ton propre salon vocal.\n\n"
        f"Un panneau de contrôle apparaît dans le salon :\n\n{CONTROL_PANEL_TEXT}\n\n"
        "Le salon disparaît automatiquement quand il se vide."
    )
    info_embed = discord.Embed(description=info_text, color=discord.Color(COLORS["saphir"]))
    if await post_once(info_channel, bot.user.id, info_embed, "Saphir · Hub vocal info"):
        report.append("📝 Message d'explication poste")
    return report


def banniere_au_hasard():
    try:
        gifs = [f for f in os.listdir(BANNIERES_DIR) if f.endswith(".gif")]
    except FileNotFoundError:
        return None
    return os.path.join(BANNIERES_DIR, random.choice(gifs)) if gifs else None


def proprietaire(channel):
    """Le propriétaire d'un salon perso : le membre qui a « Gérer le salon » dans ses
    permissions de salon. Lu sur Discord, donc juste même après un redémarrage."""
    for cible, perms in channel.overwrites.items():
        if isinstance(cible, discord.Member) and perms.manage_channels:
            return cible
    return None


def exclus(channel) -> list:
    return [c for c, p in channel.overwrites.items() if isinstance(c, discord.Member) and p.connect is False]


def est_verrouille(channel) -> bool:
    return channel.overwrites_for(channel.guild.default_role).connect is False


def est_masque(channel) -> bool:
    return channel.overwrites_for(channel.guild.default_role).view_channel is False


def build_control_embed(channel, banniere_url=None) -> discord.Embed:
    owner = proprietaire(channel)
    humains = [m for m in channel.members if not m.bot]
    limite = f" / {channel.user_limit}" if channel.user_limit else ""
    embed = discord.Embed(
        title=f"🎧 {channel.name}",
        description=("Ton salon, tes règles. Tout se gère avec les boutons ci-dessous.\n"
                     "-# Seul le propriétaire peut s'en servir."),
        color=COULEUR_PANNEAU,
    )
    if owner is not None:
        embed.set_author(name=f"Salon de {owner.display_name}", icon_url=owner.display_avatar.url)
    embed.add_field(name="👑 Propriétaire", value=owner.mention if owner else "*personne — 🙋 Réclamer*")
    embed.add_field(name="👥 Membres", value=f"**{len(humains)}**{limite}")
    embed.add_field(name="🎚️ Qualité", value=f"{channel.bitrate // 1000} kbps")
    embed.add_field(name="🔐 Accès", value="🔒 Verrouillé (sur invitation)" if est_verrouille(channel) else "🔓 Ouvert à tous")
    embed.add_field(name="👁️ Visibilité", value="🙈 Masqué" if est_masque(channel) else "👀 Visible")
    nb_exclus = len(exclus(channel))
    embed.add_field(name="⛔ Exclus", value=str(nb_exclus) if nb_exclus else "aucun")
    if banniere_url:
        embed.set_image(url=banniere_url)
    embed.set_footer(text="Le salon disparaît tout seul quand il se vide.")
    return embed


async def trouver_panneau(channel, bot_user):
    """Le message du panneau dans le chat du salon vocal (parmi les 30 derniers)."""
    try:
        async for m in channel.history(limit=30):
            if m.author.id == bot_user.id and m.components and m.embeds:
                return m
    except discord.HTTPException:
        pass
    return None


async def rafraichir_panneau(channel, client):
    """Remet le panneau à jour après un changement (verrou, propriétaire, exclus…)."""
    msg = await trouver_panneau(channel, client.user)
    if msg is None:
        return
    url = msg.embeds[0].image.url if msg.embeds and msg.embeds[0].image else None
    try:
        await msg.edit(embed=build_control_embed(channel, url), view=VoiceControlView(channel))
    except discord.HTTPException:
        pass


class RenameModal(discord.ui.Modal, title="✏️ Renommer le salon"):
    name = discord.ui.TextInput(label="Nouveau nom", max_length=90, placeholder="🔊 Salon de...")

    def __init__(self, channel: discord.VoiceChannel):
        super().__init__()
        self.channel = channel

    async def on_submit(self, interaction: discord.Interaction):
        try:
            await self.channel.edit(name=str(self.name.value))
        except discord.HTTPException:
            await interaction.response.send_message(
                "❌ Impossible de renommer le salon (il a peut-être disparu, ou permissions insuffisantes). "
                "Discord limite aussi à 2 renommages toutes les 10 minutes.",
                ephemeral=True,
            )
            return
        await interaction.response.send_message(f"✏️ Salon renommé en **{self.name.value}**.", ephemeral=True)
        await rafraichir_panneau(self.channel, interaction.client)


class LimitModal(discord.ui.Modal, title="🔢 Limite de places"):
    limit = discord.ui.TextInput(label="Nombre de places (0 = illimité)", max_length=2, placeholder="0-99")

    def __init__(self, channel: discord.VoiceChannel):
        super().__init__()
        self.channel = channel

    async def on_submit(self, interaction: discord.Interaction):
        try:
            value = max(0, min(99, int(str(self.limit.value))))
        except ValueError:
            await interaction.response.send_message("Entre un nombre valide.", ephemeral=True)
            return
        try:
            await self.channel.edit(user_limit=value)
        except discord.HTTPException:
            await interaction.response.send_message(
                "❌ Impossible de changer la limite (le salon a peut-être disparu, ou permissions insuffisantes).",
                ephemeral=True,
            )
            return
        label = "illimitée" if value == 0 else str(value)
        await interaction.response.send_message(f"🔢 Limite fixée à **{label}**.", ephemeral=True)
        await rafraichir_panneau(self.channel, interaction.client)


async def _dans_le_chat(channel, texte, pings=()):
    """Petit message public dans le chat du salon vocal (invitation, réintégration…)."""
    try:
        await channel.send(texte, allowed_mentions=discord.AllowedMentions(users=list(pings)))
    except discord.HTTPException:
        pass


async def transferer(channel, nouveau, raison):
    """Passe les droits de gestion du salon à `nouveau`."""
    ancien = proprietaire(channel)
    if ancien is not None and ancien != nouveau:
        perms = channel.overwrites_for(ancien)
        perms.update(manage_channels=None, move_members=None, mute_members=None, deafen_members=None)
        await channel.set_permissions(ancien, overwrite=None if perms.is_empty() else perms, reason=raison)
    perms = channel.overwrites_for(nouveau)
    perms.update(manage_channels=True, move_members=True, mute_members=True, deafen_members=True,
                 connect=True, view_channel=True)
    await channel.set_permissions(nouveau, overwrite=perms, reason=raison)


class MemberPickSelect(discord.ui.Select):
    """Choix d'un membre : ceux du salon (muet, exclure, transférer), ou les exclus
    (réintégrer)."""

    def __init__(self, channel: discord.VoiceChannel, action: str):
        self.channel = channel
        self.action = action
        if action == "unexclude":
            candidats = exclus(channel)
        else:
            owner = proprietaire(channel)
            candidats = [m for m in channel.members if not m.bot
                         and not (action in ("exclude", "transfer") and m == owner)]
        options = [discord.SelectOption(label=m.display_name[:100], value=str(m.id)) for m in candidats][:25]
        vide = "Aucun exclu" if action == "unexclude" else "Personne d'autre dans le salon"
        super().__init__(
            placeholder="Choisis un membre..." if options else vide,
            options=options or [discord.SelectOption(label="—", value="none")],
            disabled=not options,
        )

    async def callback(self, interaction: discord.Interaction):
        member = self.channel.guild.get_member(int(self.values[0]))
        if member is None:
            await interaction.response.send_message("Ce membre n'est plus sur le serveur.", ephemeral=True)
            return

        if self.action == "unexclude":
            perms = self.channel.overwrites_for(member)
            perms.connect = None
            await self.channel.set_permissions(member, overwrite=None if perms.is_empty() else perms,
                                               reason=f"Réintégré par {interaction.user}")
            await interaction.response.send_message(f"↩️ {member.display_name} peut revenir dans le salon.",
                                                    ephemeral=True)
            await _dans_le_chat(self.channel, f"↩️ {member.mention}, tu es réintégré : tu peux revenir.", [member])
            await rafraichir_panneau(self.channel, interaction.client)
            return

        if member.voice is None or member.voice.channel != self.channel:
            await interaction.response.send_message("Ce membre n'est plus dans le salon.", ephemeral=True)
            return

        if self.action == "mute":
            new_state = not member.voice.mute
            await member.edit(mute=new_state)
            cog = interaction.client.get_cog("VoiceHub")
            if cog is not None:
                if new_state:
                    cog.panel_muted[member.id] = self.channel.id
                else:
                    cog.panel_muted.pop(member.id, None)
            verb = "rendu muet" if new_state else "démute"
            await interaction.response.send_message(f"🔇 {member.display_name} a été {verb}.", ephemeral=True)
        elif self.action == "exclude":
            await self.channel.set_permissions(member, connect=False, reason=f"Exclu du salon par {interaction.user}")
            await member.move_to(None, reason="Exclu du salon vocal")
            await interaction.response.send_message(
                f"⛔ {member.display_name} a été exclu. **↩️ Réintégrer** pour le laisser revenir.", ephemeral=True)
            await rafraichir_panneau(self.channel, interaction.client)
        elif self.action == "transfer":
            await transferer(self.channel, member, raison=f"Transféré par {interaction.user}")
            await interaction.response.send_message(f"👑 {member.display_name} est le nouveau propriétaire.",
                                                    ephemeral=True)
            await _dans_le_chat(self.channel, f"👑 {member.mention} prend les commandes du salon.", [member])
            await rafraichir_panneau(self.channel, interaction.client)


class InviteSelect(discord.ui.UserSelect):
    """N'importe quel membre du serveur : il pourra entrer même si le salon est
    verrouillé ou masqué."""

    def __init__(self, channel):
        super().__init__(placeholder="Qui inviter ?", min_values=1, max_values=5)
        self.channel = channel

    async def callback(self, interaction: discord.Interaction):
        invites = []
        for member in self.values:
            if member.bot or not isinstance(member, discord.Member):
                continue
            perms = self.channel.overwrites_for(member)
            perms.update(connect=True, view_channel=True)
            await self.channel.set_permissions(member, overwrite=perms, reason=f"Invité par {interaction.user}")
            invites.append(member)
        if not invites:
            await interaction.response.send_message("Personne à inviter.", ephemeral=True)
            return
        await interaction.response.send_message(
            f"🤝 Invité(s) : {', '.join(m.display_name for m in invites)}. "
            "Ils peuvent entrer même si le salon est verrouillé.", ephemeral=True)
        mentions = " ".join(m.mention for m in invites)
        await _dans_le_chat(self.channel, f"🤝 {mentions}, {interaction.user.display_name} t'invite dans ce salon.",
                            invites)


class MemberPickView(discord.ui.View):
    def __init__(self, channel: discord.VoiceChannel, action: str):
        super().__init__(timeout=60)
        self.add_item(InviteSelect(channel) if action == "invite" else MemberPickSelect(channel, action))


class VoiceControlView(discord.ui.View):
    """Le panneau. Persistant (custom_id fixes) : les boutons marchent encore après un
    redémarrage. `channel` sert seulement à afficher l'état des bascules (verrou,
    visibilité) ; la vue enregistrée au démarrage n'en a pas besoin."""

    def __init__(self, channel=None):
        super().__init__(timeout=None)
        if channel is not None:
            if est_verrouille(channel):
                self.lock.label, self.lock.emoji, self.lock.style = "Déverrouiller", "🔓", discord.ButtonStyle.success
            if est_masque(channel):
                self.hide.label, self.hide.emoji, self.hide.style = "Afficher", "👀", discord.ButtonStyle.success

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        """Propriétaire du salon ou admin du serveur. Exception : 🙋 Réclamer, ouvert à
        ceux qui sont dans le salon quand le propriétaire est parti."""
        if interaction.data.get("custom_id") == "saphir_voice_claim":
            return True
        if interaction.user == proprietaire(interaction.channel) or interaction.user.guild_permissions.administrator:
            return True
        await interaction.response.send_message("👑 Seul le propriétaire du salon peut faire ça.", ephemeral=True)
        return False

    async def _choisir(self, interaction, question, action):
        await interaction.response.send_message(question, view=MemberPickView(interaction.channel, action),
                                                ephemeral=True)

    async def _apres(self, interaction, texte):
        """Met le panneau à jour directement (c'est le message cliqué), puis confirme."""
        channel = interaction.channel
        url = None
        if interaction.message and interaction.message.embeds and interaction.message.embeds[0].image:
            url = interaction.message.embeds[0].image.url
        await interaction.response.edit_message(embed=build_control_embed(channel, url),
                                                view=VoiceControlView(channel))
        await interaction.followup.send(texte, ephemeral=True)

    async def _basculer(self, interaction, champ, actif_avant, texte_on, texte_off, verbe):
        channel = interaction.channel
        perms = channel.overwrites_for(channel.guild.default_role)
        setattr(perms, champ, None if actif_avant else False)
        await channel.set_permissions(channel.guild.default_role, overwrite=None if perms.is_empty() else perms,
                                      reason=f"Salon {verbe} par {interaction.user}")
        await self._apres(interaction, texte_off if actif_avant else texte_on)

    # ── ligne 1 : le salon ──

    @discord.ui.button(label="Renommer", style=discord.ButtonStyle.secondary, emoji="✏️", custom_id="saphir_voice_rename", row=0)
    async def rename(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(RenameModal(interaction.channel))

    @discord.ui.button(label="Limite", style=discord.ButtonStyle.secondary, emoji="🔢", custom_id="saphir_voice_limit", row=0)
    async def limit(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(LimitModal(interaction.channel))

    @discord.ui.button(label="Verrouiller", style=discord.ButtonStyle.secondary, emoji="🔒", custom_id="saphir_voice_lock", row=0)
    async def lock(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._basculer(interaction, "connect", est_verrouille(interaction.channel),
                             "🔒 Salon verrouillé : seuls les invités (🤝) et ceux déjà dedans restent.",
                             "🔓 Salon ouvert à tous.", "verrouillé/déverrouillé")

    @discord.ui.button(label="Masquer", style=discord.ButtonStyle.secondary, emoji="👁️", custom_id="saphir_voice_hide", row=0)
    async def hide(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._basculer(interaction, "view_channel", est_masque(interaction.channel),
                             "🙈 Salon masqué : invisible pour les autres, sauf les invités (🤝).",
                             "👀 Salon de nouveau visible.", "masqué/affiché")

    # ── ligne 2 : les membres ──

    @discord.ui.button(label="Inviter", style=discord.ButtonStyle.success, emoji="🤝", custom_id="saphir_voice_invite", row=1)
    async def invite(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._choisir(interaction, "Qui veux-tu inviter (même si le salon est verrouillé) ?", "invite")

    @discord.ui.button(label="Muet", style=discord.ButtonStyle.secondary, emoji="🔇", custom_id="saphir_voice_mute", row=1)
    async def mute(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._choisir(interaction, "Qui veux-tu rendre muet / démute ?", "mute")

    @discord.ui.button(label="Exclure", style=discord.ButtonStyle.danger, emoji="⛔", custom_id="saphir_voice_exclude", row=1)
    async def exclude(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._choisir(interaction, "Qui veux-tu exclure du salon ?", "exclude")

    @discord.ui.button(label="Réintégrer", style=discord.ButtonStyle.secondary, emoji="↩️", custom_id="saphir_voice_unexclude", row=1)
    async def unexclude(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._choisir(interaction, "Qui laisser revenir ?", "unexclude")

    # ── ligne 3 : la propriété ──

    @discord.ui.button(label="Transférer", style=discord.ButtonStyle.secondary, emoji="👑", custom_id="saphir_voice_transfer", row=2)
    async def transfer(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._choisir(interaction, "À qui donner le salon ?", "transfer")

    @discord.ui.button(label="Réclamer", style=discord.ButtonStyle.secondary, emoji="🙋", custom_id="saphir_voice_claim", row=2)
    async def claim(self, interaction: discord.Interaction, button: discord.ui.Button):
        channel, user = interaction.channel, interaction.user
        owner = proprietaire(channel)
        if owner == user:
            await interaction.response.send_message("👑 C'est déjà ton salon.", ephemeral=True)
            return
        if user.voice is None or user.voice.channel != channel:
            await interaction.response.send_message("Il faut être dans le salon pour le réclamer.", ephemeral=True)
            return
        if owner is not None and owner.voice is not None and owner.voice.channel == channel:
            await interaction.response.send_message(f"👑 {owner.display_name} est encore là, son salon reste le sien.",
                                                    ephemeral=True)
            return
        await transferer(channel, user, raison="Salon réclamé (propriétaire parti)")
        await self._apres(interaction, "🙋 Le salon est à toi.")
        await _dans_le_chat(channel, f"🙋 {user.mention} a repris le salon, son propriétaire était parti.")


class VoiceHub(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.spawn_cooldowns = {}
        # mutes poses via le bouton "Muet" du panneau : {member_id: channel_id}. Sert a
        # rendre le mute LOCAL au salon -- des que le membre change de salon vocal, on le
        # demute. Un mute serveur classique le suivrait partout, ce que l'auteur ne veut pas.
        self.panel_muted = {}
        # IDs des salons perso crees par le hub, a supprimer une fois vides
        self.temp_channels = set()
        bot.add_view(VoiceControlView())
        self.cleanup_empty.start()

    def cog_unload(self):
        self.cleanup_empty.cancel()

    def _is_temp(self, channel, hub_id) -> bool:
        """Vrai si `channel` est un salon perso cree par le hub (par ID suivi en memoire,
        sinon par prefixe de nom pour survivre a un redemarrage)."""
        if not isinstance(channel, discord.VoiceChannel):
            return False
        if hub_id is not None and channel.id == hub_id:
            return False
        return channel.id in self.temp_channels or channel.name.startswith(TEMP_CHANNEL_PREFIX)

    @tasks.loop(seconds=120)
    async def cleanup_empty(self):
        """Balaie les salons perso VIDES et les supprime. La suppression sur départ ne se
        déclenche que quand quelqu'un quitte : un salon resté vide (redemarrage du bot,
        dernier membre parti pendant une coupure) ne serait jamais nettoye sans ce balayage.
        On ignore les salons de moins de 60 s pour ne pas supprimer un salon fraichement cree
        avant que son proprietaire n'y soit deplace."""
        settings = await aload_json(GUILD_SETTINGS_FILE, {})
        now = discord.utils.utcnow()
        for guild in self.bot.guilds:
            hub_id = settings.get(str(guild.id), {}).get("voice_hub_channel_id")
            for channel in list(guild.voice_channels):
                if not self._is_temp(channel, hub_id):
                    continue
                if len(channel.members) > 0:
                    continue
                if (now - channel.created_at).total_seconds() < 60:
                    continue
                self.temp_channels.discard(channel.id)
                try:
                    await channel.delete(reason="Salon vocal temporaire vide (balayage)")
                except (discord.NotFound, discord.Forbidden):
                    pass

    @cleanup_empty.before_loop
    async def before_cleanup_empty(self):
        await self.bot.wait_until_ready()

    @cleanup_empty.error
    async def cleanup_empty_error(self, error: Exception):
        print(f"[!] cleanup_empty a plante ({type(error).__name__}: {error}) -- redemarrage")
        self.cleanup_empty.restart()

    @app_commands.command(
        name="setup-vocal",
        description="Crée la catégorie vocale et le salon '➕ Créer un salon' pour les vocaux temporaires",
    )
    @app_commands.checks.has_permissions(administrator=True)
    async def setup_vocal(self, interaction: discord.Interaction):
        await interaction.response.defer(thinking=True, ephemeral=True)
        report = await run_setup(self.bot, interaction.guild)
        embed = discord.Embed(
            title="🎧 Configuration vocale",
            description="\n".join(report),
            color=discord.Color(COLORS["saphir"]),
        )
        await interaction.followup.send(embed=embed, ephemeral=True)

    @setup_vocal.error
    async def setup_vocal_error(self, interaction: discord.Interaction, error: app_commands.AppCommandError):
        await handle_app_error(
            interaction, error,
            perm_message="Seul un administrateur peut utiliser cette commande.",
            command_label="setup-vocal",
        )

    @app_commands.command(
        name="definir-hub-vocal",
        description="Choisis le salon vocal qui cree les salons perso (utile s'il a ete renomme)",
    )
    @app_commands.describe(salon="Le salon vocal que les membres rejoindront pour obtenir leur propre salon")
    @app_commands.checks.has_permissions(administrator=True)
    async def definir_hub_vocal(self, interaction: discord.Interaction, salon: discord.VoiceChannel):
        settings = await aload_json(GUILD_SETTINGS_FILE, {})
        settings.setdefault(str(interaction.guild.id), {})["voice_hub_channel_id"] = salon.id
        await asave_json(GUILD_SETTINGS_FILE, settings)
        await interaction.response.send_message(
            f"✅ **{salon.name}** est maintenant le salon-hub : rejoins-le pour créer un salon perso.\n"
            "Tu peux supprimer les autres salons « Créer un salon » en double s'il y en a.",
            ephemeral=True,
        )

    @definir_hub_vocal.error
    async def definir_hub_vocal_error(self, interaction: discord.Interaction, error: app_commands.AppCommandError):
        await handle_app_error(
            interaction, error,
            perm_message="Seul un administrateur peut definir le hub vocal.",
            command_label="definir-hub-vocal",
        )

    @commands.Cog.listener()
    async def on_voice_state_update(
        self, member: discord.Member, before: discord.VoiceState, after: discord.VoiceState
    ):
        guild = member.guild

        settings = await aload_json(GUILD_SETTINGS_FILE, {})
        hub_id = settings.get(str(guild.id), {}).get("voice_hub_channel_id")

        def _is_hub(channel):
            # par ID d'abord (resiste au renommage), sinon repli sur le nom exact pour les
            # serveurs configures avant l'ajout de cet ID
            if channel is None:
                return False
            if hub_id is not None:
                return channel.id == hub_id
            return channel.name == VOICE_HUB_CHANNEL_NAME

        # joined the hub -> spawn a personal channel
        if _is_hub(after.channel) and before.channel != after.channel:
            # anti-spam : on ignore les allers-retours trop rapprochés dans le hub
            now = time.time()
            if now - self.spawn_cooldowns.get(member.id, 0) < SPAWN_COOLDOWN_SECONDS:
                return
            self.spawn_cooldowns[member.id] = now

            category = after.channel.category
            overwrites = dict(after.channel.overwrites)
            overwrites[member] = discord.PermissionOverwrite(
                manage_channels=True,
                move_members=True,
                mute_members=True,
                deafen_members=True,
                connect=True,
                view_channel=True,
            )
            try:
                new_channel = await guild.create_voice_channel(
                    f"{TEMP_CHANNEL_PREFIX}{member.display_name}",
                    category=category,
                    overwrites=overwrites,
                    reason="Salon vocal temporaire",
                )
            except discord.HTTPException as e:
                print(f"⚠️ VoiceHub : création du salon impossible ({e})")
                return

            # on retient l'ID pour savoir plus tard qu'il faut le supprimer une fois vide,
            # sans dependre de sa categorie (le hub peut etre dans n'importe quelle categorie)
            self.temp_channels.add(new_channel.id)

            try:
                await member.move_to(new_channel, reason="Salon vocal temporaire")
            except discord.HTTPException:
                self.temp_channels.discard(new_channel.id)
                await new_channel.delete(reason="Déplacement impossible")
                return

            try:
                gif = banniere_au_hasard()
                fichier = discord.File(gif, filename="banniere.gif") if gif else None
                extra = {"file": fichier} if fichier else {}
                await new_channel.send(
                    content=member.mention,
                    embed=build_control_embed(new_channel, "attachment://banniere.gif" if fichier else None),
                    view=VoiceControlView(new_channel),
                    allowed_mentions=discord.AllowedMentions(users=[member]),
                    **extra,
                )
            except discord.HTTPException as e:
                print(f"⚠️ VoiceHub : panneau non envoyé ({e})")

        # demute local : si un membre mute via le panneau rejoint un AUTRE salon vocal, on
        # retire son mute serveur (le mute ne devait valoir que dans le salon d'origine).
        # S'il est deconnecte (after.channel is None) on le garde en memoire et on demutera
        # a sa prochaine connexion ailleurs -- on ne peut pas editer l'etat vocal hors salon.
        muted_channel_id = self.panel_muted.get(member.id)
        if muted_channel_id is not None and after.channel is not None and after.channel.id != muted_channel_id:
            self.panel_muted.pop(member.id, None)
            try:
                await member.edit(mute=False, reason="Demute automatique (changement de salon)")
            except discord.HTTPException:
                pass

        # quitte un salon perso -> le supprimer une fois vide. On le reconnait par son ID
        # (salons crees pendant cette session) OU par son prefixe de nom (repli qui survit a
        # un redemarrage du bot, ou le set en memoire serait perdu). Independant de la
        # categorie : le bug precedent exigeait la categorie 🎧 VOCAL, mais un hub place
        # ailleurs (ex : 🎧 · Appel) creait ses salons ailleurs, jamais supprimes.
        left = before.channel
        if left and not _is_hub(left) and len(left.members) == 0:
            is_temp = left.id in self.temp_channels or left.name.startswith(TEMP_CHANNEL_PREFIX)
            if is_temp:
                self.temp_channels.discard(left.id)
                try:
                    await left.delete(reason="Salon vocal temporaire vide")
                except (discord.NotFound, discord.Forbidden):
                    pass


async def setup(bot):
    await bot.add_cog(VoiceHub(bot))
