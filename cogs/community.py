import discord
from discord import app_commands
from discord.ext import commands

from cogs._shared import handle_app_error
from config import COLORS, COMMUNITY_CATEGORY_NAME, COMMUNITY_CHANNELS
from services.setup_kit import adopt_category, adopt_text_channel, post_once, readonly_overwrites


async def run_setup(bot, guild: discord.Guild) -> list:
    """Crée (ou adopte) la catégorie Communauté et ses salons de vie du serveur.
    Appelable par /setup-communaute et par /setup-tout. N'efface aucun salon : les salons
    proches déjà présents sont renommés/déplacés dans le thème, pas dupliqués."""
    report = []

    category, line = await adopt_category(
        guild, COMMUNITY_CATEGORY_NAME,
        keywords=["communaute", "community", "accueil", "lobby"],
    )
    report.append(line)
    if category is None:
        return report

    channels = {}
    for name, readonly, keywords in COMMUNITY_CHANNELS:
        overwrites = readonly_overwrites(guild) if readonly else None
        channel, line = await adopt_text_channel(
            guild, name, category=category, keywords=keywords, overwrites=overwrites
        )
        report.append(line)
        channels[name] = channel

    # message d'accueil dans le salon de bienvenue (posté une seule fois)
    welcome = channels.get("👋・bienvenue")
    if welcome is not None:
        embed = discord.Embed(
            title="👋 Bienvenue !",
            description=(
                "Ravi de t'avoir parmi nous. Fais un tour des salons, présente-toi dans "
                "**💬・général**, et gagne des niveaux en discutant et en vocal "
                "(voir **📊・infos-niveaux**).\n\nAmuse-toi bien 💠"
            ),
            color=discord.Color(COLORS["saphir"]),
        )
        if await post_once(welcome, bot.user.id, embed, "Saphir · Bienvenue"):
            report.append("📝 Message de bienvenue posté")

    # règlement (posté une seule fois, à compléter par le staff)
    rules = channels.get("📜・règlement")
    if rules is not None:
        embed = discord.Embed(
            title="📜 Règlement",
            description=(
                "**1.** Respecte tout le monde — pas d'insultes, de harcèlement ni de haine.\n"
                "**2.** Pas de spam, de pub non autorisée ni de contenu choquant.\n"
                "**3.** Reste dans le bon salon pour chaque sujet.\n"
                "**4.** Pas de partage de données personnelles (les tiennes ou celles des autres).\n"
                "**5.** Les décisions du staff font foi.\n\n"
                "_Le staff peut compléter ce règlement._"
            ),
            color=discord.Color(COLORS["saphir"]),
        )
        if await post_once(rules, bot.user.id, embed, "Saphir · Règlement"):
            report.append("📝 Règlement posté")

    return report


class Community(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(
        name="setup-communaute",
        description="Crée la catégorie Communauté et ses salons (annonces, général, jeux, partage...)",
    )
    @app_commands.checks.has_permissions(administrator=True)
    async def setup_communaute(self, interaction: discord.Interaction):
        await interaction.response.defer(thinking=True, ephemeral=True)
        report = await run_setup(self.bot, interaction.guild)
        embed = discord.Embed(
            title="💠 Configuration Communauté",
            description="\n".join(report),
            color=discord.Color(COLORS["saphir"]),
        )
        await interaction.followup.send(embed=embed, ephemeral=True)

    @setup_communaute.error
    async def setup_communaute_error(self, interaction: discord.Interaction, error: app_commands.AppCommandError):
        await handle_app_error(
            interaction, error,
            perm_message="Seul un administrateur peut utiliser cette commande.",
            command_label="setup-communaute",
        )


async def setup(bot):
    await bot.add_cog(Community(bot))
