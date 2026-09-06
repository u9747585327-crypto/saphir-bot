import discord
from discord.ext import commands

from config import COLORS

# ordre d'affichage + titre de section par module de cog (le "+help" reste lisible
# même quand on ajoute des commandes, tant qu'un nouveau cog est ajouté à cette liste)
SECTIONS = [
    ("cogs.scan", "💎 Scan & clonage de serveur"),
    ("cogs.hierarchy", "🎖️ Hiérarchie de rôles"),
    ("cogs.autorole", "🧩 Rôles automatiques"),
    ("cogs.voicehub", "🎧 Salons vocaux temporaires"),
    ("cogs.bringall", "🔊 Déplacement vocal"),
    ("cogs.honeypot", "🍯 Anti-bot"),
    ("cogs.prison", "🔒 Alcatraz"),
    ("cogs.logs", "📋 Logs"),
    ("cogs.leveling", "📊 Niveaux"),
    ("cogs.brawlstars", "🎮 Brawl Stars"),
    ("cogs.moderation", "🔨 Modération"),
    ("cogs.broadcast", "📨 Messages privés"),
    ("cogs.funchat", "🤖 Chat IA"),
    ("cogs.diagnostic", "🩺 Diagnostic"),
]


def build_command_fields(bot: commands.Bot, guild: discord.Guild) -> list:
    """Retourne une liste de (titre, valeur) prête à ajouter comme champs d'embed —
    réutilisé par +help et par le salon d'explication de /setup-administration."""
    all_commands = bot.tree.get_commands(guild=guild)
    by_module = {}
    for cmd in all_commands:
        by_module.setdefault(cmd.module, []).append(cmd)

    fields = []
    seen = set()
    for module_name, title in SECTIONS:
        cmds = by_module.get(module_name)
        if not cmds:
            continue
        seen.add(module_name)
        value = "\n".join(f"`/{c.name}` — {c.description}" for c in sorted(cmds, key=lambda c: c.name))
        fields.append((title, value))

    # filet de sécurité : un cog ajouté plus tard mais pas encore listé dans SECTIONS
    # apparaît quand même, sous son nom de module brut, plutôt que de disparaître.
    for module_name, cmds in by_module.items():
        if module_name in seen:
            continue
        value = "\n".join(f"`/{c.name}` — {c.description}" for c in sorted(cmds, key=lambda c: c.name))
        fields.append((module_name, value))

    return fields


class Help(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.command(name="help")
    async def help_command(self, ctx: commands.Context):
        if ctx.guild is None:
            await ctx.send("Utilise cette commande sur un serveur, pas en MP.")
            return

        fields = build_command_fields(self.bot, ctx.guild)
        if not fields:
            await ctx.send("Aucune commande synchronisée pour l'instant — réessaie dans quelques secondes.")
            return

        embed = discord.Embed(
            title="💎 Commandes de Saphir",
            description=(
                "Toutes les commandes ci-dessous sont des **slash commands** : tape `/` dans le "
                "champ de message pour les voir avec l'auto-complétion."
            ),
            color=discord.Color(COLORS["saphir"]),
        )
        for title, value in fields:
            embed.add_field(name=title, value=value, inline=False)

        embed.set_footer(text="+help pour revoir cette liste")
        await ctx.send(embed=embed)


async def setup(bot):
    await bot.add_cog(Help(bot))
