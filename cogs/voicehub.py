import time

import discord
from discord import app_commands
from discord.ext import commands

from cogs._shared import handle_app_error
from storage import aload_json, asave_json
from services.setup_kit import (
    ensure_category,
    ensure_role,
    ensure_text_channel,
    ensure_voice_channel,
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
    "✏️ **Renommer** — change le nom du salon\n"
    "🔢 **Limite** — fixe un nombre de places max\n"
    "🔇 **Muet** — rend un membre muet dans le salon\n"
    "⛔ **Exclure** — déconnecte et bloque un membre"
)


async def run_setup(bot, guild: discord.Guild) -> list:
    """Logique de /setup-vocal, appelable aussi par /setup-tout."""
    report = []

    # role donne pendant qu'un membre est en vocal (cogs/voicerole.py) : personne ne le
    # creait jusqu'ici, donc la feature ne faisait rien du tout
    _role, line = await ensure_role(guild, VOICE_ROLE_NAME)
    report.append(line)

    category, line = await ensure_category(guild, VOICE_HUB_CATEGORY_NAME)
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
        hub, line = await ensure_voice_channel(guild, VOICE_HUB_CHANNEL_NAME, category=category)
        report.append(line)

    # on memorise l'ID du hub : le listener le repere par ID, pas par nom, pour survivre
    # a un renommage (renommer le salon cassait silencieusement la creation de salons)
    if isinstance(hub, discord.VoiceChannel):
        guild_settings["voice_hub_channel_id"] = hub.id
        await asave_json(GUILD_SETTINGS_FILE, settings)

    info_channel, line = await ensure_text_channel(
        guild, VOICE_HUB_INFO_CHANNEL_NAME, category=category, overwrites=readonly_overwrites(guild)
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


def build_control_embed(owner: discord.Member) -> discord.Embed:
    embed = discord.Embed(
        title="🎧 Ton salon vocal",
        description=(
            f"{owner.mention} est aux commandes. Utilise les boutons ci-dessous pour gérer ton salon :\n\n"
            + CONTROL_PANEL_TEXT
        ),
        color=discord.Color(COLORS["saphir"]),
    )
    embed.set_footer(text="Le salon disparaît automatiquement quand il se vide.")
    return embed


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
                "❌ Impossible de renommer le salon (il a peut-être disparu, ou permissions insuffisantes).",
                ephemeral=True,
            )
            return
        await interaction.response.send_message(f"Salon renommé en **{self.name.value}**.", ephemeral=True)


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
        await interaction.response.send_message(f"Limite fixée à **{label}**.", ephemeral=True)


class MemberPickSelect(discord.ui.Select):
    def __init__(self, channel: discord.VoiceChannel, action: str):
        self.channel = channel
        self.action = action
        options = [
            discord.SelectOption(label=m.display_name, value=str(m.id))
            for m in channel.members
            if not m.bot
        ][:25]
        super().__init__(
            placeholder="Choisis un membre..." if options else "Personne dans le salon",
            options=options or [discord.SelectOption(label="—", value="none")],
            disabled=not options,
        )

    async def callback(self, interaction: discord.Interaction):
        member = self.channel.guild.get_member(int(self.values[0]))
        if member is None or member.voice is None or member.voice.channel != self.channel:
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
            await self.channel.set_permissions(member, connect=False, reason="Exclu du salon vocal")
            await member.move_to(None, reason="Exclu du salon vocal")
            await interaction.response.send_message(f"⛔ {member.display_name} a été exclu du salon.", ephemeral=True)


class MemberPickView(discord.ui.View):
    def __init__(self, channel: discord.VoiceChannel, action: str):
        super().__init__(timeout=60)
        self.add_item(MemberPickSelect(channel, action))


class VoiceControlView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    def _is_owner(self, interaction: discord.Interaction) -> bool:
        perms = interaction.channel.permissions_for(interaction.user)
        return perms.manage_channels

    @discord.ui.button(label="Renommer", style=discord.ButtonStyle.secondary, emoji="✏️", custom_id="saphir_voice_rename")
    async def rename(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not self._is_owner(interaction):
            await interaction.response.send_message("Seul le propriétaire du salon peut faire ça.", ephemeral=True)
            return
        await interaction.response.send_modal(RenameModal(interaction.channel))

    @discord.ui.button(label="Limite", style=discord.ButtonStyle.secondary, emoji="🔢", custom_id="saphir_voice_limit")
    async def limit(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not self._is_owner(interaction):
            await interaction.response.send_message("Seul le propriétaire du salon peut faire ça.", ephemeral=True)
            return
        await interaction.response.send_modal(LimitModal(interaction.channel))

    @discord.ui.button(label="Muet", style=discord.ButtonStyle.secondary, emoji="🔇", custom_id="saphir_voice_mute")
    async def mute(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not self._is_owner(interaction):
            await interaction.response.send_message("Seul le propriétaire du salon peut faire ça.", ephemeral=True)
            return
        await interaction.response.send_message(
            "Qui veux-tu rendre muet / démute ?", view=MemberPickView(interaction.channel, "mute"), ephemeral=True
        )

    @discord.ui.button(label="Exclure", style=discord.ButtonStyle.danger, emoji="⛔", custom_id="saphir_voice_exclude")
    async def exclude(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not self._is_owner(interaction):
            await interaction.response.send_message("Seul le propriétaire du salon peut faire ça.", ephemeral=True)
            return
        await interaction.response.send_message(
            "Qui veux-tu exclure du salon ?", view=MemberPickView(interaction.channel, "exclude"), ephemeral=True
        )


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
                await new_channel.send(embed=build_control_embed(member), view=VoiceControlView())
            except discord.HTTPException:
                pass

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
