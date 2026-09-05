import discord
from discord import app_commands
from discord.ext import commands

from config import AUTO_ROLE_NAME, COLORS, GUILD_SETTINGS_FILE
from storage import load_json, save_json


def get_auto_role(guild: discord.Guild):
    settings = load_json(GUILD_SETTINGS_FILE, {})
    role_id = settings.get(str(guild.id), {}).get("auto_role_id")
    if role_id:
        role = guild.get_role(role_id)
        if role:
            return role
    return discord.utils.get(guild.roles, name=AUTO_ROLE_NAME)


class AutoRole(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        role = get_auto_role(member.guild)
        if role is None:
            return
        try:
            await member.add_roles(role, reason="Rôle automatique à l'arrivée")
        except discord.Forbidden:
            pass

    @app_commands.command(
        name="set-role-membre",
        description="Choisit quel rôle donner automatiquement aux nouveaux membres (et via /donner-role-membre)",
    )
    @app_commands.describe(role="Rôle à utiliser comme rôle Membre")
    @app_commands.checks.has_permissions(administrator=True)
    async def set_role_membre(self, interaction: discord.Interaction, role: discord.Role):
        settings = load_json(GUILD_SETTINGS_FILE, {})
        settings.setdefault(str(interaction.guild.id), {})["auto_role_id"] = role.id
        save_json(GUILD_SETTINGS_FILE, settings)
        await interaction.response.send_message(
            f"✅ {role.mention} sera désormais donné automatiquement aux nouveaux membres.", ephemeral=True
        )

    @app_commands.command(
        name="donner-role-membre",
        description="Donne le rôle Membre à tous les membres du serveur qui ne l'ont pas encore",
    )
    @app_commands.checks.has_permissions(administrator=True)
    async def donner_role_membre(self, interaction: discord.Interaction):
        guild = interaction.guild
        role = get_auto_role(guild)
        if role is None:
            await interaction.response.send_message(
                "Aucun rôle Membre configuré. Utilise `/set-role-membre` pour en choisir un.", ephemeral=True
            )
            return

        await interaction.response.defer(thinking=True, ephemeral=True)

        given, skipped, failed = 0, 0, 0
        for member in guild.members:
            if member.bot:
                continue
            if role in member.roles:
                skipped += 1
                continue
            try:
                await member.add_roles(role, reason=f"/donner-role-membre par {interaction.user}")
                given += 1
            except discord.Forbidden:
                failed += 1

        embed = discord.Embed(
            title="✅ Rôle distribué",
            description=(
                f"**{given}** membre(s) ont reçu {role.mention}.\n"
                f"**{skipped}** l'avaient déjà.\n"
                f"**{failed}** échec(s) (permissions)."
            ),
            color=discord.Color(COLORS["saphir"]),
        )
        await interaction.followup.send(embed=embed, ephemeral=True)

    @set_role_membre.error
    @donner_role_membre.error
    async def autorole_error(self, interaction: discord.Interaction, error: app_commands.AppCommandError):
        if isinstance(error, app_commands.MissingPermissions):
            await interaction.response.send_message("Seul un administrateur peut utiliser cette commande.", ephemeral=True)


async def setup(bot):
    await bot.add_cog(AutoRole(bot))
