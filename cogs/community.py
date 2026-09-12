import discord
from discord import app_commands
from discord.ext import commands

from cogs._shared import handle_app_error
from config import (
    COLORS,
    COMMUNITY_CATEGORY_NAME,
    COMMUNITY_CHANNELS,
    INFOS_CATEGORY_NAME,
    INFOS_CHANNELS,
)
from services.setup_kit import adopt_category, adopt_text_channel, normalize, post_once, readonly_overwrites


async def _build_category(guild, cat_name, cat_keywords, channel_specs, report) -> dict:
    """Crée/adopte une catégorie et ses salons, renvoie {nom_canonique: salon}."""
    category, line = await adopt_category(guild, cat_name, keywords=cat_keywords)
    report.append(line)
    channels = {}
    if category is None:
        return channels
    for name, readonly, keywords in channel_specs:
        overwrites = readonly_overwrites(guild) if readonly else None
        channel, line = await adopt_text_channel(
            guild, name, category=category, keywords=keywords, overwrites=overwrites
        )
        report.append(line)
        channels[name] = channel
    return channels


async def run_setup(bot, guild: discord.Guild) -> list:
    """Crée/adopte deux catégories : INFOS (annonces + règlement, lecture seule) et
    COMMUNAUTÉ (salons de discussion où les membres écrivent). Appelable par /setup-infos et
    /setup-tout. N'efface aucun salon : les salons proches sont renommés/déplacés, pas dupliqués."""
    report = []

    infos = await _build_category(
        guild, INFOS_CATEGORY_NAME, ["info", "infos", "annonces"], INFOS_CHANNELS, report
    )
    await _build_category(
        guild, COMMUNITY_CATEGORY_NAME,
        ["communaute", "community", "chat", "general", "discussion", "accueil"],
        COMMUNITY_CHANNELS, report,
    )

    # règlement (posté une seule fois dans le salon règlement d'INFOS), style clair et complet
    rules = next((ch for nm, ch in infos.items() if normalize(nm) == "reglement"), None)
    if rules is not None:
        embed = discord.Embed(
            title="📜 Règlement de la communauté",
            description="En rejoignant et en restant sur ce serveur, tu acceptes l'ensemble de ces règles.",
            color=discord.Color(COLORS["saphir"]),
        )
        embed.add_field(
            name="1 · Respect",
            value="Reste courtois avec tout le monde. Insultes, harcèlement, menaces, propos "
                  "haineux, racistes, sexistes, homophobes ou discriminatoires sont **interdits** et sanctionnés.",
            inline=False,
        )
        embed.add_field(
            name="2 · Spam & publicité",
            value="Pas de flood, de spam de mentions, ni de publicité (autres serveurs, liens, "
                  "invitations, DM non sollicités) sans accord du staff.",
            inline=False,
        )
        embed.add_field(
            name="3 · Salons",
            value="Écris dans les bons salons et reste dans le sujet.",
            inline=False,
        )
        embed.add_field(
            name="4 · Sécurité",
            value="⚠️ Le staff ne te contactera **jamais en premier en DM**. Méfie-toi des "
                  "usurpateurs, vérifie toujours les rôles, et ne partage pas tes informations personnelles.",
            inline=False,
        )
        embed.add_field(
            name="5 · Contenu interdit",
            value="Aucun contenu NSFW, choquant, doxxing, malware, ni contenu illégal.",
            inline=False,
        )
        embed.add_field(
            name="6 · Discord",
            value="Tu dois avoir **13 ans minimum** et respecter les Conditions d'utilisation de Discord.",
            inline=False,
        )
        embed.add_field(
            name="7 · Sanctions",
            value="Selon la gravité : avertissement, exclusion (kick) ou bannissement. "
                  "Les décisions du staff sont finales.",
            inline=False,
        )
        embed.set_footer(text="Merci de faire de cette communauté un endroit sûr et agréable 💙")
        if await post_once(rules, bot.user.id, embed, "Saphir · Règlement"):
            report.append("📝 Règlement posté")

    return report


class Community(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(
        name="setup-infos",
        description="Crée les catégories INFOS (annonces + règlement) et COMMUNAUTÉ (salons de discussion)",
    )
    @app_commands.checks.has_permissions(administrator=True)
    async def setup_infos(self, interaction: discord.Interaction):
        await interaction.response.defer(thinking=True, ephemeral=True)
        report = await run_setup(self.bot, interaction.guild)
        embed = discord.Embed(
            title="📢 Configuration INFOS",
            description="\n".join(report),
            color=discord.Color(COLORS["saphir"]),
        )
        await interaction.followup.send(embed=embed, ephemeral=True)

    @setup_infos.error
    async def setup_infos_error(self, interaction: discord.Interaction, error: app_commands.AppCommandError):
        await handle_app_error(
            interaction, error,
            perm_message="Seul un administrateur peut utiliser cette commande.",
            command_label="setup-infos",
        )


async def setup(bot):
    await bot.add_cog(Community(bot))
