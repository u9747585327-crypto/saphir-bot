import asyncio

import discord
from discord import app_commands
from discord.ext import commands

from cogs._shared import SaphirModal

# délai entre deux MP quand il y en a plusieurs, pour éviter de se faire repérer/rate-limiter par Discord
DM_SEND_DELAY_SECONDS = 1.0


class ConfirmBroadcastView(discord.ui.View):
    def __init__(self, author_id: int):
        super().__init__(timeout=300)
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
        if view.value is None:
            await interaction.edit_original_response(content="⏱️ Confirmation expirée, envoi annulé.", view=None)
            return
        if not view.value:
            await interaction.edit_original_response(content="Envoi annulé.", view=None)
            return
        await interaction.edit_original_response(content=f"⏳ Envoi en cours... (0/{len(targets)})", view=None)
    else:
        await interaction.response.defer(thinking=True, ephemeral=True)

    total = len(targets)
    multi = total > 1
    sent, failed = 0, 0
    for i, target in enumerate(targets, start=1):
        try:
            await target.send(f"📨 Message de la part de **{interaction.guild.name}** :\n\n{message}")
            sent += 1
        except discord.HTTPException:
            failed += 1
        if multi:
            # point d'avancement régulier : rassure l'admin et confirme que l'envoi progresse
            if i % 20 == 0:
                try:
                    await interaction.edit_original_response(content=f"⏳ Envoi en cours... ({i}/{total})")
                except discord.HTTPException:
                    pass
            await asyncio.sleep(DM_SEND_DELAY_SECONDS)

    summary = f"✅ Envoyé à {sent} membre(s)."
    if failed:
        summary += f" ⚠️ {failed} membre(s) injoignable(s) (MP fermés)."

    # le récap DOIT arriver même si l'envoi a duré plus de 15 min (jeton d'interaction expiré) :
    # on tente le followup éphémère, puis on se rabat sur un MP à l'auteur si ça échoue.
    try:
        await interaction.followup.send(summary, ephemeral=True)
    except discord.HTTPException as e:
        print(f"⚠️ Récap /mp indisponible via l'interaction ({e}) — repli sur un MP à l'auteur")
        try:
            await interaction.user.send(f"(Saphir) Récap de ton envoi sur **{interaction.guild.name}** : {summary}")
        except discord.HTTPException:
            print(f"⚠️ Récap /mp : impossible de joindre l'auteur en MP non plus. Résultat : {summary}")


class BroadcastMessageModal(SaphirModal, title="📨 Message à envoyer"):
    error_label = "mp"
    message = discord.ui.TextInput(label="Message", style=discord.TextStyle.paragraph, max_length=1900)

    def __init__(self, targets: list, label: str):
        super().__init__()
        self.targets = targets
        self.label = label

    async def on_submit(self, interaction: discord.Interaction):
        await _send_broadcast(interaction, self.targets, str(self.message.value), self.label)


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
    @app_commands.checks.has_permissions(administrator=True)
    async def mp_tous(self, interaction: discord.Interaction):
        targets = [m for m in interaction.guild.members if not m.bot]
        label = f"**tout le serveur** ({len(targets)} membre(s))"
        await interaction.response.send_modal(BroadcastMessageModal(targets, label))

    @app_commands.command(name="mp-role", description="Envoie un MP à tous les membres ayant un rôle donné")
    @app_commands.describe(role="Rôle dont les membres recevront le message")
    @app_commands.checks.has_permissions(administrator=True)
    async def mp_role(self, interaction: discord.Interaction, role: discord.Role):
        targets = [m for m in role.members if not m.bot]
        label = f"tous les {role.mention} ({len(targets)} membre(s))"
        await interaction.response.send_modal(BroadcastMessageModal(targets, label))

    @app_commands.command(name="mp-membre", description="Envoie un MP à un membre précis")
    @app_commands.describe(membre="Membre à contacter")
    @app_commands.checks.has_permissions(administrator=True)
    async def mp_membre(self, interaction: discord.Interaction, membre: discord.Member):
        if membre.bot:
            await interaction.response.send_message("On ne peut pas envoyer de MP à un bot.", ephemeral=True)
            return
        await interaction.response.send_modal(BroadcastMessageModal([membre], membre.mention))

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
