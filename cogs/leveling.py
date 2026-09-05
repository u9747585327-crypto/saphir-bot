import random
import time

import discord
from discord import app_commands
from discord.ext import commands, tasks

from config import COLORS, LEVELS_DATA_FILE, LEVEL_UP_CHANNEL_NAME
from storage import load_json, save_json

TEXT_XP_MIN, TEXT_XP_MAX = 15, 25
TEXT_XP_COOLDOWN = 60  # secondes entre deux gains d'XP texte pour un même membre

VOICE_XP_MIN, VOICE_XP_MAX = 10, 20
VOICE_TICK_SECONDS = 60  # fréquence de distribution de l'XP vocal
VOICE_MIN_HUMANS = 2  # il faut au moins ce nombre d'humains dans le salon pour gagner de l'XP


def xp_needed(level: int) -> int:
    return 5 * (level ** 2) + 50 * level + 100


class Leveling(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.text_cooldowns = {}
        self.voice_tick.start()

    def cog_unload(self):
        self.voice_tick.cancel()

    @staticmethod
    def _get_user(data: dict, guild_id: int, user_id: int) -> dict:
        guild_data = data.setdefault(str(guild_id), {})
        return guild_data.setdefault(str(user_id), {"xp": 0, "level": 0})

    @staticmethod
    def _apply_xp(data: dict, member: discord.Member, amount: int):
        entry = Leveling._get_user(data, member.guild.id, member.id)
        entry["xp"] += amount
        leveled_to = None
        while entry["xp"] >= xp_needed(entry["level"]):
            entry["xp"] -= xp_needed(entry["level"])
            entry["level"] += 1
            leveled_to = entry["level"]
        return leveled_to

    async def _announce_level_up(self, member: discord.Member, new_level: int, fallback_channel):
        channel = discord.utils.get(member.guild.text_channels, name=LEVEL_UP_CHANNEL_NAME) or fallback_channel
        if channel is None:
            return
        embed = discord.Embed(
            title="🎉 Niveau supérieur !",
            description=f"{member.mention} passe **niveau {new_level}** !",
            color=discord.Color(COLORS["gold"]),
        )
        try:
            await channel.send(embed=embed)
        except discord.HTTPException:
            pass

    # ------------------------------------------------------------------ #
    #  Setup
    # ------------------------------------------------------------------ #

    @app_commands.command(name="setup-niveaux", description="Crée le salon d'annonce des passages de niveau")
    @app_commands.checks.has_permissions(administrator=True)
    async def setup_niveaux(self, interaction: discord.Interaction):
        guild = interaction.guild
        channel = discord.utils.get(guild.text_channels, name=LEVEL_UP_CHANNEL_NAME)
        try:
            if channel is None:
                channel = await guild.create_text_channel(LEVEL_UP_CHANNEL_NAME, reason="Configuration niveaux (Saphir)")
                status = f"✅ Salon créé : {channel.mention}"
            else:
                status = f"= Salon déjà présent : {channel.mention}"
        except discord.Forbidden:
            await interaction.response.send_message("❌ Permissions insuffisantes pour créer le salon.", ephemeral=True)
            return

        await interaction.response.send_message(
            f"{status}\n\nLes passages de niveau (texte + vocal cumulés) y seront annoncés.", ephemeral=True
        )

    @setup_niveaux.error
    async def setup_niveaux_error(self, interaction: discord.Interaction, error: app_commands.AppCommandError):
        if isinstance(error, app_commands.MissingPermissions):
            await interaction.response.send_message("Seul un administrateur peut utiliser cette commande.", ephemeral=True)

    # ------------------------------------------------------------------ #
    #  Gain d'XP
    # ------------------------------------------------------------------ #

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot or not message.guild:
            return

        key = (message.guild.id, message.author.id)
        now = time.time()
        if now - self.text_cooldowns.get(key, 0) < TEXT_XP_COOLDOWN:
            return
        self.text_cooldowns[key] = now

        data = load_json(LEVELS_DATA_FILE, {})
        leveled_to = self._apply_xp(data, message.author, random.randint(TEXT_XP_MIN, TEXT_XP_MAX))
        save_json(LEVELS_DATA_FILE, data)

        if leveled_to:
            await self._announce_level_up(message.author, leveled_to, message.channel)

    @tasks.loop(seconds=VOICE_TICK_SECONDS)
    async def voice_tick(self):
        data = load_json(LEVELS_DATA_FILE, {})
        level_ups = []
        changed = False

        for guild in self.bot.guilds:
            afk_channel = guild.afk_channel
            for voice_channel in guild.voice_channels:
                if voice_channel == afk_channel:
                    continue
                humans = [m for m in voice_channel.members if not m.bot]
                if len(humans) < VOICE_MIN_HUMANS:
                    continue
                for member in humans:
                    changed = True
                    leveled_to = self._apply_xp(data, member, random.randint(VOICE_XP_MIN, VOICE_XP_MAX))
                    if leveled_to:
                        level_ups.append((member, leveled_to))

        if changed:
            save_json(LEVELS_DATA_FILE, data)

        for member, level in level_ups:
            await self._announce_level_up(member, level, None)

    @voice_tick.before_loop
    async def before_voice_tick(self):
        await self.bot.wait_until_ready()

    # ------------------------------------------------------------------ #
    #  Consultation
    # ------------------------------------------------------------------ #

    @app_commands.command(name="niveau", description="Affiche ton niveau et ton XP (ou celui d'un autre membre)")
    @app_commands.describe(membre="Membre à consulter (toi par défaut)")
    async def niveau(self, interaction: discord.Interaction, membre: discord.Member = None):
        membre = membre or interaction.user
        data = load_json(LEVELS_DATA_FILE, {})
        entry = self._get_user(data, interaction.guild.id, membre.id)

        embed = discord.Embed(title=f"📊 Niveau de {membre.display_name}", color=discord.Color(COLORS["saphir"]))
        embed.add_field(name="Niveau", value=str(entry["level"]))
        embed.add_field(name="XP", value=f"{entry['xp']} / {xp_needed(entry['level'])}")
        embed.set_thumbnail(url=membre.display_avatar.url)
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="classement", description="Classement des membres par XP sur ce serveur")
    async def classement(self, interaction: discord.Interaction):
        data = load_json(LEVELS_DATA_FILE, {})
        guild_data = data.get(str(interaction.guild.id), {})

        def total_xp(entry):
            return sum(xp_needed(l) for l in range(entry["level"])) + entry["xp"]

        ranking = sorted(guild_data.items(), key=lambda kv: total_xp(kv[1]), reverse=True)[:10]
        if not ranking:
            await interaction.response.send_message("Personne n'a encore d'XP sur ce serveur.", ephemeral=True)
            return

        lines = []
        for i, (user_id, entry) in enumerate(ranking, start=1):
            member = interaction.guild.get_member(int(user_id))
            name = member.mention if member else f"Utilisateur {user_id}"
            lines.append(f"**{i}.** {name} — niveau {entry['level']} ({total_xp(entry)} XP total)")

        embed = discord.Embed(title="🏆 Classement", description="\n".join(lines), color=discord.Color(COLORS["gold"]))
        await interaction.response.send_message(embed=embed)


async def setup(bot):
    await bot.add_cog(Leveling(bot))
