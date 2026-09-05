import discord
from discord import app_commands
from discord.ext import commands

from config import (
    COLORS,
    HIERARCHY_ROLES,
    LOGS_CATEGORY_NAME,
    PERM_JAIL_ROLE_NAME,
    PERM_UNJAIL_ROLE_NAME,
    PRISON_CATEGORY_NAME,
    STAFF_ROLE_NAMES,
)


class Hierarchy(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(
        name="setup-roles",
        description="Crée la hiérarchie de rôles (Fondateur → Membre) et les rôles Perm Jail/Perm Unjail",
    )
    @app_commands.checks.has_permissions(administrator=True)
    async def setup_roles(self, interaction: discord.Interaction):
        await interaction.response.defer(thinking=True, ephemeral=True)
        guild = interaction.guild
        report = []
        created_roles = {}

        # 1. hiérarchie de rôles avec permissions natives cumulées
        for name, color, perms in HIERARCHY_ROLES:
            role = discord.utils.get(guild.roles, name=name)
            permissions = discord.Permissions(**perms)
            try:
                if role is None:
                    role = await guild.create_role(
                        name=name, color=discord.Color(color), hoist=True, mentionable=False,
                        permissions=permissions, reason="Configuration hiérarchie (Saphir)",
                    )
                    report.append(f"✅ Rôle créé : {name}")
                else:
                    await role.edit(
                        color=discord.Color(color), hoist=True, permissions=permissions,
                        reason="Configuration hiérarchie (Saphir)",
                    )
                    report.append(f"🔄 Rôle mis à jour : {name}")
                created_roles[name] = role
            except discord.Forbidden:
                report.append(f"❌ Rôle refusé (permissions) : {name}")

        # 2. ordre de préséance : du plus haut (index 0) au plus bas
        try:
            positions = {
                role: len(HIERARCHY_ROLES) - i
                for i, (name, *_rest) in enumerate(HIERARCHY_ROLES)
                if (role := created_roles.get(name)) is not None
            }
            if positions:
                await guild.edit_role_positions(positions=positions)
        except (discord.Forbidden, discord.HTTPException):
            report.append("⚠️ Ordre des rôles non réappliqué (rôle du bot probablement trop bas)")

        # 3. rôles de permission autonomes (Perm Jail / Perm Unjail)
        for name in (PERM_JAIL_ROLE_NAME, PERM_UNJAIL_ROLE_NAME):
            role = discord.utils.get(guild.roles, name=name)
            try:
                if role is None:
                    await guild.create_role(
                        name=name, hoist=False, mentionable=False, reason="Configuration permissions (Saphir)"
                    )
                    report.append(f"✅ Rôle créé : {name}")
                else:
                    report.append(f"= Rôle déjà présent : {name}")
            except discord.Forbidden:
                report.append(f"❌ Rôle refusé (permissions) : {name}")

        # 4. accès staff aux catégories Alcatraz et Logs (au-delà du bypass Administrateur)
        staff_roles = [created_roles[n] for n in STAFF_ROLE_NAMES if n in created_roles]
        for category_name in (PRISON_CATEGORY_NAME, LOGS_CATEGORY_NAME):
            category = discord.utils.get(guild.categories, name=category_name)
            if category is None or not staff_roles:
                continue
            for role in staff_roles:
                try:
                    await category.set_permissions(role, view_channel=True, reason="Accès staff (Saphir)")
                except discord.Forbidden:
                    pass
            report.append(f"🔑 Accès staff appliqué sur {category_name}")

        embed = discord.Embed(
            title="🎖️ Configuration des rôles",
            description="\n".join(report),
            color=discord.Color(COLORS["saphir"]),
        )
        await interaction.followup.send(embed=embed, ephemeral=True)

    @setup_roles.error
    async def setup_roles_error(self, interaction: discord.Interaction, error: app_commands.AppCommandError):
        if isinstance(error, app_commands.MissingPermissions):
            await interaction.response.send_message("Seul un administrateur peut utiliser cette commande.", ephemeral=True)


async def setup(bot):
    await bot.add_cog(Hierarchy(bot))
