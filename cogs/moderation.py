import discord
from discord import app_commands
from discord.ext import commands

from cogs.prison import parse_duration
from config import COLORS, LOG_CHANNELS

MAX_TIMEOUT_DAYS = 28


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
    @app_commands.describe(membre="Membre à expulser", raison="Raison de l'expulsion")
    @app_commands.checks.has_permissions(kick_members=True)
    async def kick(self, interaction: discord.Interaction, membre: discord.Member, raison: str = "Non spécifiée"):
        try:
            await membre.kick(reason=f"{interaction.user} : {raison}")
        except discord.Forbidden:
            await interaction.response.send_message("❌ Impossible d'expulser ce membre (rôle trop haut ou permissions insuffisantes).", ephemeral=True)
            return

        embed = discord.Embed(title="🥾 Membre expulsé", color=discord.Color(COLORS["danger"]))
        embed.add_field(name="Membre", value=f"{membre} ({membre.id})", inline=False)
        embed.add_field(name="Modérateur", value=interaction.user.mention)
        embed.add_field(name="Raison", value=raison, inline=False)
        await interaction.response.send_message(embed=embed)
        await self._log(interaction.guild, embed)

    @app_commands.command(name="ban", description="Bannit un membre du serveur")
    @app_commands.describe(
        membre="Membre à bannir",
        raison="Raison du bannissement",
        jours_messages="Supprimer les messages des N derniers jours (0-7)",
    )
    @app_commands.checks.has_permissions(ban_members=True)
    async def ban(
        self,
        interaction: discord.Interaction,
        membre: discord.Member,
        raison: str = "Non spécifiée",
        jours_messages: app_commands.Range[int, 0, 7] = 0,
    ):
        try:
            await membre.ban(reason=f"{interaction.user} : {raison}", delete_message_days=jours_messages)
        except discord.Forbidden:
            await interaction.response.send_message("❌ Impossible de bannir ce membre (rôle trop haut ou permissions insuffisantes).", ephemeral=True)
            return

        embed = discord.Embed(title="🔨 Membre banni", color=discord.Color(COLORS["danger"]))
        embed.add_field(name="Membre", value=f"{membre} ({membre.id})", inline=False)
        embed.add_field(name="Modérateur", value=interaction.user.mention)
        embed.add_field(name="Raison", value=raison, inline=False)
        await interaction.response.send_message(embed=embed)
        await self._log(interaction.guild, embed)

    @app_commands.command(name="unban", description="Débannit un membre via son ID Discord")
    @app_commands.describe(user_id="ID Discord du membre à débannir", raison="Raison")
    @app_commands.checks.has_permissions(ban_members=True)
    async def unban(self, interaction: discord.Interaction, user_id: str, raison: str = "Non spécifiée"):
        try:
            user = discord.Object(id=int(user_id))
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
        embed.add_field(name="ID", value=user_id, inline=False)
        embed.add_field(name="Modérateur", value=interaction.user.mention)
        embed.add_field(name="Raison", value=raison, inline=False)
        await interaction.response.send_message(embed=embed)
        await self._log(interaction.guild, embed)

    @app_commands.command(name="mute", description="Rend un membre muet temporairement (timeout Discord)")
    @app_commands.describe(membre="Membre à rendre muet", duree="Durée, ex : 10m, 2h, 1d (28 jours max)", raison="Raison")
    @app_commands.checks.has_permissions(moderate_members=True)
    async def mute(self, interaction: discord.Interaction, membre: discord.Member, duree: str, raison: str = "Non spécifiée"):
        try:
            delta = parse_duration(duree)
        except ValueError as e:
            await interaction.response.send_message(f"❌ {e}", ephemeral=True)
            return

        if delta.days > MAX_TIMEOUT_DAYS:
            await interaction.response.send_message(f"❌ Discord limite le timeout à {MAX_TIMEOUT_DAYS} jours maximum.", ephemeral=True)
            return

        try:
            await membre.timeout(delta, reason=f"{interaction.user} : {raison}")
        except discord.Forbidden:
            await interaction.response.send_message("❌ Impossible de mettre ce membre en sourdine.", ephemeral=True)
            return

        embed = discord.Embed(title="🔇 Membre mis en sourdine", color=discord.Color(COLORS["gold"]))
        embed.add_field(name="Membre", value=membre.mention, inline=False)
        embed.add_field(name="Durée", value=duree)
        embed.add_field(name="Modérateur", value=interaction.user.mention)
        embed.add_field(name="Raison", value=raison, inline=False)
        await interaction.response.send_message(embed=embed)
        await self._log(interaction.guild, embed)

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
    @app_commands.describe(membre="Membre à avertir", raison="Raison de l'avertissement")
    @app_commands.checks.has_permissions(moderate_members=True)
    async def avertir(self, interaction: discord.Interaction, membre: discord.Member, raison: str):
        embed = discord.Embed(title="⚠️ Avertissement", color=discord.Color(COLORS["gold"]))
        embed.add_field(name="Membre", value=membre.mention, inline=False)
        embed.add_field(name="Modérateur", value=interaction.user.mention)
        embed.add_field(name="Raison", value=raison, inline=False)
        await interaction.response.send_message(embed=embed)
        await self._log(interaction.guild, embed)
        try:
            await membre.send(f"⚠️ Tu as reçu un avertissement sur **{interaction.guild.name}** : {raison}")
        except discord.HTTPException:
            pass

    @app_commands.command(name="clear", description="Supprime des messages récents dans ce salon")
    @app_commands.describe(nombre="Nombre de messages à supprimer (1-100)", membre="Ne supprimer que les messages de ce membre (optionnel)")
    @app_commands.checks.has_permissions(manage_messages=True)
    async def clear(self, interaction: discord.Interaction, nombre: app_commands.Range[int, 1, 100], membre: discord.Member = None):
        await interaction.response.defer(thinking=True, ephemeral=True)
        check = (lambda m: m.author.id == membre.id) if membre else None
        deleted = await interaction.channel.purge(limit=nombre, check=check)
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
            await interaction.response.send_message("Tu n'as pas la permission de faire ça.", ephemeral=True)


async def setup(bot):
    await bot.add_cog(Moderation(bot))
