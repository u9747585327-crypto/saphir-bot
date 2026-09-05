import discord
from discord import app_commands
from discord.ext import commands

import storage
from config import (
    COLORS,
    EXILE_ROLE_NAME,
    HIERARCHY_ROLES,
    HONEYPOT_CHANNEL_NAME,
    LEVEL_ROLES,
    LEVELS_CATEGORY_NAME,
    LOG_CHANNELS,
    LOGS_CATEGORY_NAME,
    PERM_JAIL_ROLE_NAME,
    PERM_UNJAIL_ROLE_NAME,
    PRISON_CATEGORY_NAME,
    VOICE_HUB_CATEGORY_NAME,
    VOICE_HUB_CHANNEL_NAME,
)


def _check_role(guild: discord.Guild, name: str) -> str:
    return "✅" if discord.utils.get(guild.roles, name=name) else "❌ manquant"


def _check_category(guild: discord.Guild, name: str) -> str:
    return "✅" if discord.utils.get(guild.categories, name=name) else "❌ manquante"


def _check_channel(guild: discord.Guild, name: str) -> str:
    found = discord.utils.get(guild.text_channels, name=name) or discord.utils.get(guild.voice_channels, name=name)
    return "✅" if found else "❌ manquant"


class Diagnostic(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(
        name="diagnostic",
        description="Rapport complet de l'état du serveur : config, rôles/salons manquants, doublons",
    )
    @app_commands.checks.has_permissions(administrator=True)
    async def diagnostic(self, interaction: discord.Interaction):
        await interaction.response.defer(thinking=True, ephemeral=True)
        guild = interaction.guild
        lines = []

        # --- Bot lui-même ---
        bot_top_role = guild.me.top_role
        lines.append(f"**Rôle du bot** : {bot_top_role.mention} (position {bot_top_role.position}/{len(guild.roles) - 1})")
        if bot_top_role.position < len(guild.roles) - 4:
            lines.append("⚠️ Le rôle du bot est peut-être trop bas dans la liste — monte-le pour éviter des erreurs de permissions.")

        lines.append(f"**Stockage** : {'✅ MongoDB connecté' if storage.is_connected() else '⚠️ Fichiers locaux (perdus au redémarrage sur Render)'}")

        # --- Doublons ---
        role_counts = {}
        for role in guild.roles:
            role_counts[role.name] = role_counts.get(role.name, 0) + 1
        dup_roles = [n for n, c in role_counts.items() if c > 1]

        channel_counts = {}
        for ch in guild.channels:
            channel_counts[ch.name] = channel_counts.get(ch.name, 0) + 1
        dup_channels = [n for n, c in channel_counts.items() if c > 1]

        lines.append("")
        lines.append("**Doublons :**")
        if dup_roles:
            lines.append(f"❌ Rôles en double ({len(dup_roles)}) : " + ", ".join(f"`{n}` x{role_counts[n]}" for n in dup_roles))
        else:
            lines.append("✅ Aucun rôle en double (nom exact)")
        if dup_channels:
            lines.append(f"❌ Salons en double ({len(dup_channels)}) : " + ", ".join(f"`{n}` x{channel_counts[n]}" for n in dup_channels))
        else:
            lines.append("✅ Aucun salon en double (nom exact)")

        # --- Fonctionnalités ---
        lines.append("")
        lines.append("**Fonctionnalités :**")

        lines.append(f"🔒 Prison — catégorie {_check_category(guild, PRISON_CATEGORY_NAME)}, rôle Exilé {_check_role(guild, EXILE_ROLE_NAME)}")

        logs_found = sum(1 for c in LOG_CHANNELS.values() if discord.utils.get(guild.text_channels, name=c))
        lines.append(f"📋 Logs — catégorie {_check_category(guild, LOGS_CATEGORY_NAME)}, {logs_found}/{len(LOG_CHANNELS)} salons")

        level_roles_found = sum(1 for _, n, _ in LEVEL_ROLES if discord.utils.get(guild.roles, name=n))
        lines.append(f"📊 Niveaux — catégorie {_check_category(guild, LEVELS_CATEGORY_NAME)}, {level_roles_found}/{len(LEVEL_ROLES)} rôles de niveau")

        lines.append(f"🍯 Honeypot — salon {_check_channel(guild, HONEYPOT_CHANNEL_NAME)}")

        lines.append(
            f"🎧 Hub vocal — catégorie {_check_category(guild, VOICE_HUB_CATEGORY_NAME)}, "
            f"salon {_check_channel(guild, VOICE_HUB_CHANNEL_NAME)}"
        )

        hierarchy_found = sum(1 for n, _, _ in HIERARCHY_ROLES if discord.utils.get(guild.roles, name=n))
        lines.append(
            f"🎖️ Hiérarchie — {hierarchy_found}/{len(HIERARCHY_ROLES)} rôles, "
            f"Perm Jail {_check_role(guild, PERM_JAIL_ROLE_NAME)}, Perm Unjail {_check_role(guild, PERM_UNJAIL_ROLE_NAME)}"
        )

        description = "\n".join(lines)
        chunks = [description[i:i + 3900] for i in range(0, len(description), 3900)] or ["Rien à signaler."]
        for i, chunk in enumerate(chunks):
            embed = discord.Embed(
                title="🩺 Diagnostic du serveur" if i == 0 else "🩺 (suite)",
                description=chunk,
                color=discord.Color(COLORS["saphir"]),
            )
            await interaction.followup.send(embed=embed, ephemeral=True)

    @diagnostic.error
    async def diagnostic_error(self, interaction: discord.Interaction, error: app_commands.AppCommandError):
        if isinstance(error, app_commands.MissingPermissions):
            await interaction.response.send_message("Seul un administrateur peut utiliser cette commande.", ephemeral=True)


async def setup(bot):
    await bot.add_cog(Diagnostic(bot))
