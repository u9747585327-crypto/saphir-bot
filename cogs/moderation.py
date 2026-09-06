import discord
from discord import app_commands
from discord.ext import commands

from cogs._shared import SaphirModal
from cogs.prison import parse_duration
from config import COLORS, LOG_CHANNELS

MAX_TIMEOUT_DAYS = 28


class KickModal(SaphirModal, title="🥾 Expulser un membre"):
    error_label = "kick"
    raison = discord.ui.TextInput(label="Raison", required=False, placeholder="Non spécifiée", max_length=500)

    def __init__(self, cog: "Moderation", membre: discord.Member):
        super().__init__()
        self.cog = cog
        self.membre = membre

    async def on_submit(self, interaction: discord.Interaction):
        raison = str(self.raison.value) or "Non spécifiée"
        try:
            await self.membre.kick(reason=f"{interaction.user} : {raison}")
        except discord.Forbidden:
            await interaction.response.send_message(
                "❌ Impossible d'expulser ce membre (rôle trop haut ou permissions insuffisantes).", ephemeral=True
            )
            return

        embed = discord.Embed(title="🥾 Membre expulsé", color=discord.Color(COLORS["danger"]))
        embed.add_field(name="Membre", value=f"{self.membre} ({self.membre.id})", inline=False)
        embed.add_field(name="Modérateur", value=interaction.user.mention)
        embed.add_field(name="Raison", value=raison, inline=False)
        await interaction.response.send_message(embed=embed)
        await self.cog._log(interaction.guild, embed)


class BanModal(SaphirModal, title="🔨 Bannir un membre"):
    error_label = "ban"
    raison = discord.ui.TextInput(label="Raison", required=False, placeholder="Non spécifiée", max_length=500)

    def __init__(self, cog: "Moderation", membre: discord.Member, jours_messages: int):
        super().__init__()
        self.cog = cog
        self.membre = membre
        self.jours_messages = jours_messages

    async def on_submit(self, interaction: discord.Interaction):
        raison = str(self.raison.value) or "Non spécifiée"
        try:
            await self.membre.ban(reason=f"{interaction.user} : {raison}", delete_message_days=self.jours_messages)
        except discord.Forbidden:
            await interaction.response.send_message(
                "❌ Impossible de bannir ce membre (rôle trop haut ou permissions insuffisantes).", ephemeral=True
            )
            return

        embed = discord.Embed(title="🔨 Membre banni", color=discord.Color(COLORS["danger"]))
        embed.add_field(name="Membre", value=f"{self.membre} ({self.membre.id})", inline=False)
        embed.add_field(name="Modérateur", value=interaction.user.mention)
        embed.add_field(name="Raison", value=raison, inline=False)
        await interaction.response.send_message(embed=embed)
        await self.cog._log(interaction.guild, embed)


class UnbanModal(SaphirModal, title="🔓 Débannir un membre"):
    error_label = "unban"
    user_id = discord.ui.TextInput(label="ID Discord du membre à débannir", max_length=25)
    raison = discord.ui.TextInput(label="Raison", required=False, placeholder="Non spécifiée", max_length=500)

    def __init__(self, cog: "Moderation"):
        super().__init__()
        self.cog = cog

    async def on_submit(self, interaction: discord.Interaction):
        raison = str(self.raison.value) or "Non spécifiée"
        raw_id = str(self.user_id.value)
        try:
            user = discord.Object(id=int(raw_id))
        except ValueError:
            await interaction.response.send_message("❌ ID invalide.", ephemeral=True)
            return

        try:
            await interaction.guild.unban(user, reason=f"{interaction.user} : {raison}")
        except discord.NotFound:
            await interaction.response.send_message("❌ Ce membre n'est pas banni.", ephemeral=True)
            return
        except discord.Forbidden:
            await interaction.response.send_message("❌ Permissions insuffisantes.", ephemeral=True)
            return

        embed = discord.Embed(title="🔓 Membre débanni", color=discord.Color(COLORS["success"]))
        embed.add_field(name="ID", value=raw_id, inline=False)
        embed.add_field(name="Modérateur", value=interaction.user.mention)
        embed.add_field(name="Raison", value=raison, inline=False)
        await interaction.response.send_message(embed=embed)
        await self.cog._log(interaction.guild, embed)


class MuteModal(SaphirModal, title="🔇 Mettre en sourdine"):
    error_label = "mute"
    duree = discord.ui.TextInput(label="Durée", placeholder="ex : 10m, 2h, 1d (28 jours max)", max_length=10)
    raison = discord.ui.TextInput(label="Raison", required=False, placeholder="Non spécifiée", max_length=500)

    def __init__(self, cog: "Moderation", membre: discord.Member):
        super().__init__()
        self.cog = cog
        self.membre = membre

    async def on_submit(self, interaction: discord.Interaction):
        duree_str = str(self.duree.value)
        raison = str(self.raison.value) or "Non spécifiée"

        try:
            delta = parse_duration(duree_str)
        except ValueError as e:
            await interaction.response.send_message(f"❌ {e}", ephemeral=True)
            return

        if delta.days > MAX_TIMEOUT_DAYS:
            await interaction.response.send_message(f"❌ Discord limite le timeout à {MAX_TIMEOUT_DAYS} jours maximum.", ephemeral=True)
            return

        try:
            await self.membre.timeout(delta, reason=f"{interaction.user} : {raison}")
        except discord.Forbidden:
            await interaction.response.send_message("❌ Impossible de mettre ce membre en sourdine.", ephemeral=True)
            return

        embed = discord.Embed(title="🔇 Membre mis en sourdine", color=discord.Color(COLORS["gold"]))
        embed.add_field(name="Membre", value=self.membre.mention, inline=False)
        embed.add_field(name="Durée", value=duree_str)
        embed.add_field(name="Modérateur", value=interaction.user.mention)
        embed.add_field(name="Raison", value=raison, inline=False)
        await interaction.response.send_message(embed=embed)
        await self.cog._log(interaction.guild, embed)


class AvertirModal(SaphirModal, title="⚠️ Avertir un membre"):
    error_label = "avertir"
    raison = discord.ui.TextInput(label="Raison", max_length=500)

    def __init__(self, cog: "Moderation", membre: discord.Member):
        super().__init__()
        self.cog = cog
        self.membre = membre

    async def on_submit(self, interaction: discord.Interaction):
        raison = str(self.raison.value)
        embed = discord.Embed(title="⚠️ Avertissement", color=discord.Color(COLORS["gold"]))
        embed.add_field(name="Membre", value=self.membre.mention, inline=False)
        embed.add_field(name="Modérateur", value=interaction.user.mention)
        embed.add_field(name="Raison", value=raison, inline=False)
        await interaction.response.send_message(embed=embed)
        await self.cog._log(interaction.guild, embed)
        try:
            await self.membre.send(f"⚠️ Tu as reçu un avertissement sur **{interaction.guild.name}** : {raison}")
        except discord.HTTPException:
            pass


class Moderation(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    async def _log(self, guild: discord.Guild, embed: discord.Embed):
        channel = discord.utils.get(guild.text_channels, name=LOG_CHANNELS["moderation"])
        if channel:
            try:
                await channel.send(embed=embed)
            except discord.HTTPException:
                pass

    @app_commands.command(name="kick", description="Expulse un membre du serveur")
    @app_commands.describe(membre="Membre à expulser")
    @app_commands.checks.has_permissions(kick_members=True)
    async def kick(self, interaction: discord.Interaction, membre: discord.Member):
        await interaction.response.send_modal(KickModal(self, membre))

    @app_commands.command(name="ban", description="Bannit un membre du serveur")
    @app_commands.describe(membre="Membre à bannir", jours_messages="Supprimer les messages des N derniers jours (0-7)")
    @app_commands.checks.has_permissions(ban_members=True)
    async def ban(self, interaction: discord.Interaction, membre: discord.Member, jours_messages: app_commands.Range[int, 0, 7] = 0):
        await interaction.response.send_modal(BanModal(self, membre, jours_messages))

    @app_commands.command(name="unban", description="Débannit un membre via son ID Discord")
    @app_commands.checks.has_permissions(ban_members=True)
    async def unban(self, interaction: discord.Interaction):
        await interaction.response.send_modal(UnbanModal(self))

    @app_commands.command(name="mute", description="Rend un membre muet temporairement (timeout Discord)")
    @app_commands.describe(membre="Membre à rendre muet")
    @app_commands.checks.has_permissions(moderate_members=True)
    async def mute(self, interaction: discord.Interaction, membre: discord.Member):
        await interaction.response.send_modal(MuteModal(self, membre))

    @app_commands.command(name="unmute", description="Retire la sourdine (timeout) d'un membre")
    @app_commands.describe(membre="Membre à démute")
    @app_commands.checks.has_permissions(moderate_members=True)
    async def unmute(self, interaction: discord.Interaction, membre: discord.Member):
        try:
            await membre.timeout(None, reason=f"Démute par {interaction.user}")
        except discord.Forbidden:
            await interaction.response.send_message("❌ Permissions insuffisantes.", ephemeral=True)
            return

        embed = discord.Embed(title="🔊 Sourdine retirée", description=membre.mention, color=discord.Color(COLORS["success"]))
        await interaction.response.send_message(embed=embed)
        await self._log(interaction.guild, embed)

    @app_commands.command(name="avertir", description="Envoie un avertissement à un membre")
    @app_commands.describe(membre="Membre à avertir")
    @app_commands.checks.has_permissions(moderate_members=True)
    async def avertir(self, interaction: discord.Interaction, membre: discord.Member):
        await interaction.response.send_modal(AvertirModal(self, membre))

    @app_commands.command(name="clear", description="Supprime des messages récents dans ce salon")
    @app_commands.describe(nombre="Nombre de messages à supprimer (1-100)", membre="Ne supprimer que les messages de ce membre (optionnel)")
    @app_commands.checks.has_permissions(manage_messages=True)
    async def clear(self, interaction: discord.Interaction, nombre: app_commands.Range[int, 1, 100], membre: discord.Member = None):
        await interaction.response.defer(thinking=True, ephemeral=True)
        purge_kwargs = {"limit": nombre}
        if membre:
            purge_kwargs["check"] = lambda m: m.author.id == membre.id
        try:
            deleted = await interaction.channel.purge(**purge_kwargs)
        except discord.Forbidden:
            await interaction.followup.send(
                "❌ Le bot n'a pas la permission \"Gérer les messages\" (et/ou \"Voir l'historique\") dans ce salon.",
                ephemeral=True,
            )
            return
        await interaction.followup.send(f"🧹 {len(deleted)} message(s) supprimé(s).", ephemeral=True)

    @app_commands.command(name="lock", description="Verrouille ce salon (les membres ne peuvent plus écrire)")
    @app_commands.checks.has_permissions(manage_channels=True)
    async def lock(self, interaction: discord.Interaction):
        try:
            await interaction.channel.set_permissions(
                interaction.guild.default_role, send_messages=False, reason=f"Verrouillé par {interaction.user}"
            )
        except discord.Forbidden:
            await interaction.response.send_message("❌ Permissions insuffisantes.", ephemeral=True)
            return
        await interaction.response.send_message("🔒 Salon verrouillé.")

    @app_commands.command(name="unlock", description="Déverrouille ce salon")
    @app_commands.checks.has_permissions(manage_channels=True)
    async def unlock(self, interaction: discord.Interaction):
        try:
            await interaction.channel.set_permissions(
                interaction.guild.default_role, send_messages=None, reason=f"Déverrouillé par {interaction.user}"
            )
        except discord.Forbidden:
            await interaction.response.send_message("❌ Permissions insuffisantes.", ephemeral=True)
            return
        await interaction.response.send_message("🔓 Salon déverrouillé.")

    @app_commands.command(name="slowmode", description="Définit le mode lent de ce salon")
    @app_commands.describe(secondes="Délai en secondes entre deux messages (0 pour désactiver, 21600 max)")
    @app_commands.checks.has_permissions(manage_channels=True)
    async def slowmode(self, interaction: discord.Interaction, secondes: app_commands.Range[int, 0, 21600]):
        try:
            await interaction.channel.edit(slowmode_delay=secondes, reason=f"Slowmode par {interaction.user}")
        except discord.Forbidden:
            await interaction.response.send_message("❌ Permissions insuffisantes.", ephemeral=True)
            return
        if secondes == 0:
            await interaction.response.send_message("✅ Mode lent désactivé.")
        else:
            await interaction.response.send_message(f"🐌 Mode lent réglé sur {secondes}s.")

    @kick.error
    @ban.error
    @unban.error
    @mute.error
    @unmute.error
    @avertir.error
    @clear.error
    @lock.error
    @unlock.error
    @slowmode.error
    async def moderation_error(self, interaction: discord.Interaction, error: app_commands.AppCommandError):
        if isinstance(error, app_commands.MissingPermissions):
            message = "Tu n'as pas la permission de faire ça."
        else:
            original = getattr(error, "original", error)
            if isinstance(original, discord.Forbidden):
                message = "❌ Le bot n'a pas les permissions nécessaires pour faire ça ici."
            else:
                message = f"❌ Une erreur est survenue : {original}"
            print(f"⚠️ Erreur dans une commande de modération : {original}")

        try:
            if interaction.response.is_done():
                await interaction.followup.send(message, ephemeral=True)
            else:
                await interaction.response.send_message(message, ephemeral=True)
        except discord.HTTPException:
            pass


async def setup(bot):
    await bot.add_cog(Moderation(bot))
