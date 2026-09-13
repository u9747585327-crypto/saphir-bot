import discord
from discord import app_commands
from discord.ext import commands, tasks

from cogs._shared import handle_app_error
from config import (
    COLORS,
    GUILD_SETTINGS_FILE,
    STATS_CATEGORY_NAME,
    STATS_CHANNELS,
    STATS_REFRESH_SECONDS,
)
from services.setup_kit import adopt_category
from storage import aload_json, asave_json


def _value_for(guild: discord.Guild, key: str) -> int:
    """Valeur courante d'un compteur. Seuls les compteurs réellement lisibles par un bot
    sont ici (le nombre d'« avis » Discord n'est pas exposé par l'API)."""
    if key == "members":
        return guild.member_count or 0
    if key == "boosts":
        return guild.premium_subscription_count or 0
    return 0


def _label(template: str, value: int) -> str:
    return template.format(count=value)


async def run_setup(bot, guild: discord.Guild) -> list:
    """Crée la catégorie Statistiques et ses salons-compteurs (vocaux verrouillés : on voit
    le nombre dans le nom, mais personne ne peut s'y connecter). Les IDs sont mémorisés
    pour que la boucle de rafraîchissement retrouve les bons salons."""
    report = []
    # verrouillé : visible mais impossible à rejoindre
    locked = {guild.default_role: discord.PermissionOverwrite(connect=False)}

    category, line = await adopt_category(
        guild, STATS_CATEGORY_NAME, keywords=["stat", "stats", "statistique"],
    )
    report.append(line)
    if category is None:
        return report

    settings = await aload_json(GUILD_SETTINGS_FILE, {})
    guild_settings = settings.setdefault(str(guild.id), {})
    stats_ids = guild_settings.setdefault("stats_channel_ids", {})

    for key, template, _keywords in STATS_CHANNELS:
        value = _value_for(guild, key)
        name = _label(template, value)
        channel = guild.get_channel(stats_ids.get(key, 0))
        try:
            if isinstance(channel, discord.VoiceChannel):
                if channel.name != name or channel.category != category:
                    await channel.edit(name=name, category=category, overwrites=locked,
                                       reason="Compteur statistique (Saphir)")
                report.append(f"= Compteur déjà présent : {name}")
            else:
                channel = await guild.create_voice_channel(
                    name, category=category, overwrites=locked, reason="Compteur statistique (Saphir)"
                )
                report.append(f"✅ Compteur créé : {name}")
            stats_ids[key] = channel.id
        except discord.Forbidden:
            report.append(f"❌ Compteur refusé (permissions) : {name}")

    await asave_json(GUILD_SETTINGS_FILE, settings)
    return report


class Stats(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.refresh_stats.start()

    def cog_unload(self):
        self.refresh_stats.cancel()

    async def _update_guild(self, guild: discord.Guild, settings=None):
        """Met à jour les compteurs d'un serveur. Le renommage de salon est limité par
        Discord (~2 / 10 min par salon) : un échec est ignoré, le loop rattrapera."""
        if settings is None:
            settings = await aload_json(GUILD_SETTINGS_FILE, {})
        stats_ids = settings.get(str(guild.id), {}).get("stats_channel_ids", {})
        for key, template, _keywords in STATS_CHANNELS:
            channel = guild.get_channel(stats_ids.get(key, 0))
            if not isinstance(channel, discord.VoiceChannel):
                continue
            name = _label(template, _value_for(guild, key))
            if channel.name != name:
                try:
                    await channel.edit(name=name, reason="Mise à jour du compteur (Saphir)")
                except discord.HTTPException:
                    pass

    @tasks.loop(seconds=STATS_REFRESH_SECONDS)
    async def refresh_stats(self):
        settings = await aload_json(GUILD_SETTINGS_FILE, {})
        for guild in self.bot.guilds:
            await self._update_guild(guild, settings)

    # mise à jour réactive : dès qu'un membre arrive/part ou que le boost change, on
    # rafraîchit tout de suite (le loop de 10 min reste le filet de sécurité)
    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        await self._update_guild(member.guild)

    @commands.Cog.listener()
    async def on_member_remove(self, member: discord.Member):
        await self._update_guild(member.guild)

    @commands.Cog.listener()
    async def on_guild_update(self, before: discord.Guild, after: discord.Guild):
        if before.premium_subscription_count != after.premium_subscription_count:
            await self._update_guild(after)

    @refresh_stats.before_loop
    async def before_refresh_stats(self):
        await self.bot.wait_until_ready()

    @refresh_stats.error
    async def refresh_stats_error(self, error: Exception):
        print(f"[!] refresh_stats a plante ({type(error).__name__}: {error}) -- redemarrage")
        self.refresh_stats.restart()

    @app_commands.command(
        name="setup-stats",
        description="Crée les compteurs statistiques (membres, boosts) en salons verrouillés",
    )
    @app_commands.checks.has_permissions(administrator=True)
    async def setup_stats(self, interaction: discord.Interaction):
        await interaction.response.defer(thinking=True, ephemeral=True)
        report = await run_setup(self.bot, interaction.guild)
        embed = discord.Embed(
            title="📈 Configuration Statistiques",
            description="\n".join(report),
            color=discord.Color(COLORS["saphir"]),
        )
        await interaction.followup.send(embed=embed, ephemeral=True)

    @setup_stats.error
    async def setup_stats_error(self, interaction: discord.Interaction, error: app_commands.AppCommandError):
        await handle_app_error(
            interaction, error,
            perm_message="Seul un administrateur peut utiliser cette commande.",
            command_label="setup-stats",
        )


async def setup(bot):
    await bot.add_cog(Stats(bot))
