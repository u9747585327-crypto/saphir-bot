import re
import unicodedata

import discord
from discord import app_commands
from discord.ext import commands

import cogs.brawlstars as brawlstars
import cogs.funchat as funchat
import storage
from cogs._shared import handle_app_error
from config import COLORS, LEVEL_ROLES, LOG_CHANNELS


def _normalize(text: str) -> str:
    """Minuscules, sans accents, sans espaces/tirets/soulignés/emoji/déco — pour comparer
    des noms qui ont pu changer de style/casse/accentuation sans perdre leur sens."""
    text = unicodedata.normalize("NFKD", text)
    text = "".join(c for c in text if not unicodedata.combining(c))
    text = text.lower()
    return re.sub(r"[^a-z0-9]", "", text)


def _any_contains(names, keyword) -> bool:
    keyword = _normalize(keyword)
    return any(keyword in _normalize(n) for n in names)


def _check(names, keyword) -> str:
    return "✅" if _any_contains(names, keyword) else "❌ manquant"


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

        role_names = [r.name for r in guild.roles]
        category_names = [c.name for c in guild.categories]
        channel_names = [c.name for c in guild.channels]

        # --- Bot lui-même ---
        bot_top_role = guild.me.top_role
        lines.append(f"**Rôle du bot** : {bot_top_role.mention} (position {bot_top_role.position}/{len(guild.roles) - 1})")
        if bot_top_role.position < len(guild.roles) - 4:
            lines.append("⚠️ Le rôle du bot est peut-être trop bas dans la liste — monte-le pour éviter des erreurs de permissions.")

        lines.append(f"**Stockage** : {'✅ MongoDB connecté' if storage.is_connected() else '⚠️ Fichiers locaux (perdus au redémarrage sur Render)'}")
        lines.append(f"**Chat IA** : {'✅ Groq connecté' if funchat.is_ai_enabled() else '⚠️ Réponses toutes faites (pas de GROQ_API_KEY)'}")
        lines.append(f"**Brawl Stars** : {'✅ Clé API configurée' if brawlstars.is_configured() else '⚠️ Non configuré (pas de BRAWLSTARS_API_KEY)'}")

        # --- Doublons (nom strictement identique) ---
        role_counts = {}
        for role in guild.roles:
            role_counts[role.name] = role_counts.get(role.name, 0) + 1
        dup_roles = [n for n, c in role_counts.items() if c > 1]

        channel_counts = {}
        for ch in guild.channels:
            channel_counts[ch.name] = channel_counts.get(ch.name, 0) + 1
        dup_channels = [n for n, c in channel_counts.items() if c > 1]

        lines.append("")
        lines.append("**Doublons (nom strictement identique) :**")
        if dup_roles:
            lines.append(f"❌ Rôles en double ({len(dup_roles)}) : " + ", ".join(f"`{n}` x{role_counts[n]}" for n in dup_roles))
        else:
            lines.append("✅ Aucun rôle en double")
        if dup_channels:
            lines.append(f"❌ Salons en double ({len(dup_channels)}) : " + ", ".join(f"`{n}` x{channel_counts[n]}" for n in dup_channels))
        else:
            lines.append("✅ Aucun salon en double")

        # --- Fonctionnalités (recherche par mot-clé, insensible au style/accents/casse) ---
        lines.append("")
        lines.append("**Fonctionnalités** _(détection par mot-clé, tolère les changements de nom/style)_ :")

        lines.append(f"🔒 Prison — catégorie {_check(category_names, 'alcatraz')}, rôle Exilé {_check(role_names, 'exile')}")

        logs_found = sum(1 for c in LOG_CHANNELS.values() if _any_contains(channel_names, c))
        lines.append(f"📋 Logs — catégorie {_check(category_names, 'logs')}, {logs_found}/{len(LOG_CHANNELS)} salons")

        level_roles_found = sum(1 for _, n, _ in LEVEL_ROLES if _any_contains(role_names, n))
        lines.append(f"📊 Niveaux — catégorie {_check(category_names, 'niveaux')}, {level_roles_found}/{len(LEVEL_ROLES)} rôles de niveau")

        lines.append(f"🍯 Honeypot — salon {_check(channel_names, 'ecrireici')}")

        lines.append(f"🎧 Hub vocal — catégorie {_check(category_names, 'vocal')}, salon {_check(channel_names, 'creerunsalon')}")

        hierarchy_keywords = ["fondateur", "cofondateur", "commandant", "adminvocal", "adminchat", "membre"]
        hierarchy_found = sum(1 for kw in hierarchy_keywords if _any_contains(role_names, kw))
        lines.append(
            f"🎖️ Hiérarchie — {hierarchy_found}/{len(hierarchy_keywords)} rangs détectés, "
            f"Perm Jail {_check(role_names, 'permjail')}, Perm Unjail {_check(role_names, 'permunjail')}"
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
        await handle_app_error(
            interaction, error,
            perm_message="Seul un administrateur peut utiliser cette commande.",
            command_label="diagnostic",
        )


async def setup(bot):
    await bot.add_cog(Diagnostic(bot))
