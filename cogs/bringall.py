import discord
from discord import app_commands
from discord.ext import commands

from config import COLORS


class BringAll(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(
        name="bring-all",
        description="Déplace tous les membres connectés en vocal vers un salon (le tien par défaut)",
    )
    @app_commands.describe(salon="Salon vocal cible (par défaut : celui où tu es connecté)")
    @app_commands.checks.has_permissions(move_members=True)
    async def bring_all(self, interaction: discord.Interaction, salon: discord.VoiceChannel = None):
        guild = interaction.guild
        target = salon or (interaction.user.voice.channel if interaction.user.voice else None)

        if target is None:
            await interaction.response.send_message(
                "Connecte-toi d'abord à un salon vocal, ou précise le paramètre `salon`.",
                ephemeral=True,
            )
            return

        await interaction.response.defer(thinking=True, ephemeral=True)

        members_to_move = [
            member
            for voice_channel in guild.voice_channels
            if voice_channel != target
            for member in voice_channel.members
        ]

        moved, failed = 0, 0
        for member in members_to_move:
            try:
                await member.move_to(target, reason=f"/bring-all par {interaction.user}")
                moved += 1
            except discord.HTTPException:
                failed += 1

        description = f"**{moved}** membre(s) déplacé(s) vers {target.mention}."
        if failed:
            description += f"\n**{failed}** échec(s) (permissions ou salon plein)."
        if not members_to_move:
            description = "Personne à déplacer : aucun autre salon vocal n'est occupé."

        embed = discord.Embed(title="🔊 Bring all", description=description, color=discord.Color(COLORS["saphir"]))
        await interaction.followup.send(embed=embed, ephemeral=True)

    @bring_all.error
    async def bring_all_error(self, interaction: discord.Interaction, error: app_commands.AppCommandError):
        if isinstance(error, app_commands.MissingPermissions):
            await interaction.response.send_message(
                "Il te faut la permission de déplacer les membres pour utiliser cette commande.", ephemeral=True
            )


async def setup(bot):
    await bot.add_cog(BringAll(bot))
