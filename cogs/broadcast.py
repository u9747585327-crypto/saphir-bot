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


class Broadcast(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="mp-membres", description="Envoie un MP à un membre, un rôle, ou tous les membres du serveur")
    @app_commands.describe(
        message="Contenu du message à envoyer",
        membre="N'envoyer qu'à ce membre",
        role="Envoyer à tous les membres ayant ce rôle",
        tous="Envoyer à tous les membres du serveur (confirmation demandée)",
    )
    @app_commands.checks.has_permissions(administrator=True)
    async def mp_membres(
        self,
        interaction: discord.Interaction,
        message: str,
        membre: discord.Member = None,
        role: discord.Role = None,
        tous: bool = False,
    ):
        chosen = sum(1 for v in (membre, role, tous) if v)
        if chosen != 1:
            await interaction.response.send_message(
                "Précise exactement une cible : `membre`, `role`, ou `tous` (une seule à la fois).",
                ephemeral=True,
            )
            return

        if membre is not None:
            targets = [membre]
            label = membre.mention
        elif role is not None:
            targets = [m for m in role.members if not m.bot]
            label = f"tous les {role.mention} ({len(targets)} membre(s))"
        else:
            targets = [m for m in interaction.guild.members if not m.bot]
            label = f"**tout le serveur** ({len(targets)} membre(s))"

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

    @mp_membres.error
    async def mp_membres_error(self, interaction: discord.Interaction, error: app_commands.AppCommandError):
        if isinstance(error, app_commands.MissingPermissions):
            await interaction.response.send_message("Seul un administrateur peut utiliser cette commande.", ephemeral=True)
            return

        original = getattr(error, "original", error)
        message = f"❌ Une erreur est survenue : {original}"
        print(f"⚠️ Erreur dans /mp-membres : {original}")
        try:
            if interaction.response.is_done():
                await interaction.followup.send(message, ephemeral=True)
            else:
                await interaction.response.send_message(message, ephemeral=True)
        except discord.HTTPException:
            pass


async def setup(bot):
    await bot.add_cog(Broadcast(bot))
