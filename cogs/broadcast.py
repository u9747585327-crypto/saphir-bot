import asyncio

import discord
from discord import app_commands
from discord.ext import commands

# délai entre deux MP quand il y en a plusieurs, pour éviter de se faire repérer/rate-limiter par Discord
DM_SEND_DELAY_SECONDS = 1.0


class ConfirmBroadcastView(discord.ui.View):
    def __init__(self, author_id: int):
        super().__init__(timeout=60)
        self.author_id = author_id
        self.value = None

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.author_id:
            await interaction.response.send_message("Seul l'auteur de la commande peut confirmer.", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="Envoyer", style=discord.ButtonStyle.danger, emoji="📨")
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.value = True
        self.stop()
        await interaction.response.defer()

    @discord.ui.button(label="Annuler", style=discord.ButtonStyle.secondary)
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.value = False
        self.stop()
        await interaction.response.defer()


async def _send_broadcast(interaction: discord.Interaction, targets: list, message: str, label: str):
    """Logique commune aux 3 commandes de MP en masse : confirmation si plusieurs
    destinataires, envoi espacé, puis récap des succès/échecs."""
    if not targets:
        await interaction.response.send_message("Aucun membre à contacter pour cette cible.", ephemeral=True)
        return

    if len(targets) > 1:
        view = ConfirmBroadcastView(interaction.user.id)
        await interaction.response.send_message(
            f"⚠️ Tu vas envoyer ce MP à {label} :\n> {message}\n\nConfirmer l'envoi ?",
            view=view,
            ephemeral=True,
        )
        await view.wait()
        if not view.value:
            await interaction.edit_original_response(content="Envoi annulé.", view=None)
            return
        await interaction.edit_original_response(content="⏳ Envoi en cours...", view=None)
    else:
        await interaction.response.defer(thinking=True, ephemeral=True)

    sent, failed = 0, 0
    for target in targets:
        try:
            await target.send(f"📨 Message de la part de **{interaction.guild.name}** :\n\n{message}")
            sent += 1
        except discord.HTTPException:
            failed += 1
        if len(targets) > 1:
            await asyncio.sleep(DM_SEND_DELAY_SECONDS)

    summary = f"✅ Envoyé à {sent} membre(s)."
    if failed:
        summary += f" ⚠️ {failed} membre(s) injoignable(s) (MP fermés)."

    await interaction.followup.send(summary, ephemeral=True)


async def _broadcast_error(interaction: discord.Interaction, error: app_commands.AppCommandError, command_name: str):
    if isinstance(error, app_commands.MissingPermissions):
        await interaction.response.send_message("Seul un administrateur peut utiliser cette commande.", ephemeral=True)
        return

    original = getattr(error, "original", error)
    message = f"❌ Une erreur est survenue : {original}"
    print(f"⚠️ Erreur dans /{command_name} : {original}")
    try:
        if interaction.response.is_done():
            await interaction.followup.send(message, ephemeral=True)
        else:
            await interaction.response.send_message(message, ephemeral=True)
    except discord.HTTPException:
        pass


class Broadcast(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="mp-tous", description="Envoie un MP à tous les membres du serveur")
    @app_commands.describe(message="Contenu du message à envoyer")
    @app_commands.checks.has_permissions(administrator=True)
    async def mp_tous(self, interaction: discord.Interaction, message: str):
        targets = [m for m in interaction.guild.members if not m.bot]
        await _send_broadcast(interaction, targets, message, f"**tout le serveur** ({len(targets)} membre(s))")

    @app_commands.command(name="mp-role", description="Envoie un MP à tous les membres ayant un rôle donné")
    @app_commands.describe(role="Rôle dont les membres recevront le message", message="Contenu du message à envoyer")
    @app_commands.checks.has_permissions(administrator=True)
    async def mp_role(self, interaction: discord.Interaction, role: discord.Role, message: str):
        targets = [m for m in role.members if not m.bot]
        await _send_broadcast(interaction, targets, message, f"tous les {role.mention} ({len(targets)} membre(s))")

    @app_commands.command(name="mp-membre", description="Envoie un MP à un membre précis")
    @app_commands.describe(membre="Membre à contacter", message="Contenu du message à envoyer")
    @app_commands.checks.has_permissions(administrator=True)
    async def mp_membre(self, interaction: discord.Interaction, membre: discord.Member, message: str):
        await _send_broadcast(interaction, [membre], message, membre.mention)

    @mp_tous.error
    async def mp_tous_error(self, interaction: discord.Interaction, error: app_commands.AppCommandError):
        await _broadcast_error(interaction, error, "mp-tous")

    @mp_role.error
    async def mp_role_error(self, interaction: discord.Interaction, error: app_commands.AppCommandError):
        await _broadcast_error(interaction, error, "mp-role")

    @mp_membre.error
    async def mp_membre_error(self, interaction: discord.Interaction, error: app_commands.AppCommandError):
        await _broadcast_error(interaction, error, "mp-membre")


async def setup(bot):
    await bot.add_cog(Broadcast(bot))
