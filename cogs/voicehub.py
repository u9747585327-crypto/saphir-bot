import time

import discord
from discord import app_commands
from discord.ext import commands

from config import VOICE_HUB_CATEGORY_NAME, VOICE_HUB_CHANNEL_NAME, COLORS

# anti-spam : délai minimal entre deux créations de salon perso par le même membre
SPAWN_COOLDOWN_SECONDS = 15


def build_control_embed(owner: discord.Member) -> discord.Embed:
    embed = discord.Embed(
        title="🎧 Ton salon vocal",
        description=(
            f"{owner.mention} est aux commandes. Utilise les boutons ci-dessous pour gérer ton salon :\n\n"
            "✏️ **Renommer** — change le nom du salon\n"
            "🔢 **Limite** — fixe un nombre de places max\n"
            "🔇 **Muet** — rend un membre muet dans le salon\n"
            "⛔ **Exclure** — déconnecte et bloque un membre"
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
        bot.add_view(VoiceControlView())

    @app_commands.command(
        name="setup-vocal",
        description="Crée la catégorie vocale et le salon '➕ Créer un salon' pour les vocaux temporaires",
    )
    @app_commands.checks.has_permissions(administrator=True)
    async def setup_vocal(self, interaction: discord.Interaction):
        guild = interaction.guild

        category = discord.utils.get(guild.categories, name=VOICE_HUB_CATEGORY_NAME)
        try:
            if category is None:
                category = await guild.create_category(VOICE_HUB_CATEGORY_NAME, reason="Configuration vocal (Saphir)")
                cat_status = f"✅ Catégorie créée : {VOICE_HUB_CATEGORY_NAME}"
            else:
                cat_status = f"= Catégorie déjà présente : {VOICE_HUB_CATEGORY_NAME}"
        except discord.Forbidden:
            await interaction.response.send_message("❌ Permissions insuffisantes pour créer la catégorie.", ephemeral=True)
            return

        hub = discord.utils.get(category.channels, name=VOICE_HUB_CHANNEL_NAME)
        try:
            if hub is None:
                await guild.create_voice_channel(
                    VOICE_HUB_CHANNEL_NAME, category=category, reason="Configuration vocal (Saphir)"
                )
                hub_status = f"✅ Salon créé : {VOICE_HUB_CHANNEL_NAME}"
            else:
                hub_status = f"= Salon déjà présent : {VOICE_HUB_CHANNEL_NAME}"
        except discord.Forbidden:
            hub_status = f"❌ Salon refusé (permissions) : {VOICE_HUB_CHANNEL_NAME}"

        embed = discord.Embed(
            title="🎧 Configuration vocale",
            description=(
                f"{cat_status}\n{hub_status}\n\n"
                f"Un membre qui rejoint **{VOICE_HUB_CHANNEL_NAME}** obtient aussitôt son propre "
                "salon vocal personnel, avec un panneau de contrôle (renommer, limite, muet, exclure)."
            ),
            color=discord.Color(COLORS["saphir"]),
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @setup_vocal.error
    async def setup_vocal_error(self, interaction: discord.Interaction, error: app_commands.AppCommandError):
        if isinstance(error, app_commands.MissingPermissions):
            await interaction.response.send_message("Seul un administrateur peut utiliser cette commande.", ephemeral=True)

    @commands.Cog.listener()
    async def on_voice_state_update(
        self, member: discord.Member, before: discord.VoiceState, after: discord.VoiceState
    ):
        guild = member.guild

        # joined the hub -> spawn a personal channel
        if after.channel and after.channel.name == VOICE_HUB_CHANNEL_NAME and before.channel != after.channel:
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
                    f"🔊 Salon de {member.display_name}",
                    category=category,
                    overwrites=overwrites,
                    reason="Salon vocal temporaire",
                )
            except discord.HTTPException as e:
                print(f"⚠️ VoiceHub : création du salon impossible ({e})")
                return

            try:
                await member.move_to(new_channel, reason="Salon vocal temporaire")
            except discord.HTTPException:
                await new_channel.delete(reason="Déplacement impossible")
                return

            try:
                await new_channel.send(embed=build_control_embed(member), view=VoiceControlView())
            except discord.HTTPException:
                pass

        # left a temp channel -> delete it once empty
        if before.channel and before.channel.category and before.channel.category.name == VOICE_HUB_CATEGORY_NAME:
            if before.channel.name != VOICE_HUB_CHANNEL_NAME and len(before.channel.members) == 0:
                try:
                    await before.channel.delete(reason="Salon vocal temporaire vide")
                except discord.NotFound:
                    pass


async def setup(bot):
    await bot.add_cog(VoiceHub(bot))
