import discord
from discord import app_commands
from discord.ext import commands

from cogs import brawlstars, honeypot, logs, voicehub
from cogs._shared import handle_app_error
from config import COLORS


async def _cog_setup(bot, cog_name: str, guild, method: str = "run_setup"):
    """Appelle la méthode de setup d'un cog (les cogs qui ont besoin de leur instance,
    contrairement à ceux dont le run_setup est une simple fonction de module)."""
    cog = bot.get_cog(cog_name)
    if cog is None:
        return [f"⏭️ Cog `{cog_name}` non chargé"]
    return await getattr(cog, method)(guild)


# Ordre imposé par les dépendances réelles entre features :
#  - /setup-administration a besoin des rôles créés par /setup-roles
#  - l'étape « accès staff » de /setup-roles ne fait rien tant que les catégories
#    Alcatraz et Logs n'existent pas → d'où le second passage de setup-roles à la fin
# Le chat IA n'apparaît pas ici : il n'a plus de salon dédié (il répond au ping partout).
STEPS = [
    ("setup-roles", lambda bot, g: _cog_setup(bot, "Hierarchy", g)),
    ("setup-logs", lambda bot, g: logs.run_setup(bot, g)),
    ("setup-prison", lambda bot, g: _cog_setup(bot, "Prison", g)),
    ("setup-niveaux", lambda bot, g: _cog_setup(bot, "Leveling", g)),
    ("setup-vocal", lambda bot, g: voicehub.run_setup(bot, g)),
    ("setup-honeypot", lambda bot, g: honeypot.run_setup(bot, g)),
    ("setup-brawlstars", lambda bot, g: brawlstars.run_setup(bot, g)),
    ("setup-administration", lambda bot, g: _cog_setup(bot, "Hierarchy", g, "run_setup_administration")),
    ("setup-roles (2e passage)", lambda bot, g: _cog_setup(bot, "Hierarchy", g)),
]


class SetupAll(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(
        name="setup-tout",
        description="Lance toute la configuration du serveur, dans l'ordre imposé par les dépendances",
    )
    @app_commands.checks.has_permissions(administrator=True)
    async def setup_tout(self, interaction: discord.Interaction):
        await interaction.response.defer(thinking=True, ephemeral=True)
        guild = interaction.guild
        summary = []

        for label, step in STEPS:
            try:
                report = await step(self.bot, guild)
                failures = sum(1 for line in report if line.startswith("❌") or line.startswith("⚠️"))
                if failures:
                    summary.append(f"⚠️ `/{label}` — {failures} problème(s)")
                else:
                    summary.append(f"✅ `/{label}`")
            except Exception as e:
                print(f"⚠️ /setup-tout a échoué à l'étape {label} : {type(e).__name__}: {e}")
                summary.append(f"❌ `/{label}` — {e}")

        embed = discord.Embed(
            title="🧰 Configuration complète",
            description="\n".join(summary),
            color=discord.Color(COLORS["saphir"]),
        )
        embed.set_footer(text="Relance une commande précise pour voir son rapport détaillé")
        await interaction.followup.send(embed=embed, ephemeral=True)

    @setup_tout.error
    async def setup_tout_error(self, interaction: discord.Interaction, error: app_commands.AppCommandError):
        await handle_app_error(
            interaction, error,
            perm_message="Seul un administrateur peut utiliser cette commande.",
            command_label="setup-tout",
        )


async def setup(bot):
    await bot.add_cog(SetupAll(bot))
