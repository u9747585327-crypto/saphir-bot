import asyncio
import io
import random
import time

import discord
from discord import app_commands
from discord.ext import commands, tasks
from PIL import Image, ImageDraw, ImageFont

from config import (
    COLORS,
    GUILD_SETTINGS_FILE,
    LEADERBOARD_CHANNEL_NAME,
    LEADERBOARD_REFRESH_SECONDS,
    LEVEL_ROLES,
    LEVEL_UP_CHANNEL_NAME,
    LEVELS_CATEGORY_NAME,
    LEVELS_DATA_FILE,
)
from storage import load_json, save_json

TEXT_XP_MIN, TEXT_XP_MAX = 15, 25
TEXT_XP_COOLDOWN = 60  # secondes entre deux gains d'XP texte pour un même membre

VOICE_XP_MIN, VOICE_XP_MAX = 10, 20
VOICE_TICK_SECONDS = 60  # fréquence de distribution de l'XP vocal
VOICE_MIN_HUMANS = 2  # il faut au moins ce nombre d'humains dans le salon pour gagner de l'XP

# rendu de l'image de classement
CARD_WIDTH = 900
ROW_HEIGHT = 90
ROW_GAP = 10
HEADER_HEIGHT = 100
PADDING = 20
AVATAR_SIZE = 64

BG_COLOR = (32, 34, 37)
ROW_COLOR = (47, 49, 54)
BAR_BG_COLOR = (60, 63, 68)
ACCENT_COLOR = (31, 111, 235)  # saphir
TEXT_COLOR = (255, 255, 255)
SUBTEXT_COLOR = (185, 187, 190)
MEDAL_COLORS = [(240, 194, 88), (200, 200, 210), (205, 127, 80)]


def xp_needed(level: int) -> int:
    return 5 * (level ** 2) + 50 * level + 100


def total_xp(entry: dict) -> int:
    return sum(xp_needed(l) for l in range(entry["level"])) + entry["xp"]


def _make_circle_avatar(avatar_bytes: bytes, size: int) -> Image.Image:
    img = Image.open(io.BytesIO(avatar_bytes)).convert("RGBA").resize((size, size))
    mask = Image.new("L", (size, size), 0)
    ImageDraw.Draw(mask).ellipse((0, 0, size, size), fill=255)
    circled = Image.new("RGBA", (size, size))
    circled.paste(img, (0, 0), mask)
    return circled


def _render_leaderboard_png(guild_name: str, rows: list) -> io.BytesIO:
    height = HEADER_HEIGHT + len(rows) * (ROW_HEIGHT + ROW_GAP) + PADDING
    img = Image.new("RGB", (CARD_WIDTH, height), BG_COLOR)
    draw = ImageDraw.Draw(img)

    title_font = ImageFont.load_default(size=32)
    rank_font = ImageFont.load_default(size=24)
    name_font = ImageFont.load_default(size=22)
    sub_font = ImageFont.load_default(size=16)

    draw.rectangle((0, 0, CARD_WIDTH, HEADER_HEIGHT), fill=ACCENT_COLOR)
    draw.text((PADDING, HEADER_HEIGHT / 2 - 18), f"CLASSEMENT - {guild_name}", font=title_font, fill=TEXT_COLOR)

    y = HEADER_HEIGHT + ROW_GAP
    for i, (name, level, xp, needed, hours, avatar_img) in enumerate(rows):
        draw.rounded_rectangle((PADDING, y, CARD_WIDTH - PADDING, y + ROW_HEIGHT), radius=14, fill=ROW_COLOR)

        rank_color = MEDAL_COLORS[i] if i < 3 else SUBTEXT_COLOR
        draw.text((PADDING + 20, y + ROW_HEIGHT / 2 - 14), f"#{i + 1}", font=rank_font, fill=rank_color)

        avatar_x = PADDING + 80
        avatar_y = y + (ROW_HEIGHT - AVATAR_SIZE) // 2
        if avatar_img:
            img.paste(avatar_img, (avatar_x, avatar_y), avatar_img)
        else:
            draw.ellipse((avatar_x, avatar_y, avatar_x + AVATAR_SIZE, avatar_y + AVATAR_SIZE), fill=BAR_BG_COLOR)

        text_x = avatar_x + AVATAR_SIZE + 20
        draw.text((text_x, y + 12), name, font=name_font, fill=TEXT_COLOR)
        draw.text((text_x, y + 40), f"Niveau {level} · {hours:.1f}h vocal", font=sub_font, fill=SUBTEXT_COLOR)

        bar_x, bar_y, bar_w, bar_h = text_x, y + 66, 300, 10
        draw.rounded_rectangle((bar_x, bar_y, bar_x + bar_w, bar_y + bar_h), radius=5, fill=BAR_BG_COLOR)
        progress = min(1.0, xp / needed) if needed else 0
        if progress > 0:
            draw.rounded_rectangle(
                (bar_x, bar_y, bar_x + max(bar_h, int(bar_w * progress)), bar_y + bar_h), radius=5, fill=ACCENT_COLOR
            )
        draw.text((bar_x + bar_w + 15, bar_y - 4), f"{xp}/{needed} XP", font=sub_font, fill=SUBTEXT_COLOR)

        y += ROW_HEIGHT + ROW_GAP

    buffer = io.BytesIO()
    img.save(buffer, format="PNG")
    buffer.seek(0)
    return buffer


class Leveling(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.text_cooldowns = {}
        self.voice_tick.start()
        self.leaderboard_refresh.start()

    def cog_unload(self):
        self.voice_tick.cancel()
        self.leaderboard_refresh.cancel()

    # ------------------------------------------------------------------ #
    #  XP / niveaux
    # ------------------------------------------------------------------ #

    @staticmethod
    def _get_user(data: dict, guild_id: int, user_id: int) -> dict:
        guild_data = data.setdefault(str(guild_id), {})
        return guild_data.setdefault(str(user_id), {"xp": 0, "level": 0, "voice_seconds": 0})

    @staticmethod
    def _apply_xp(data: dict, member: discord.Member, amount: int, voice_seconds: int = 0):
        entry = Leveling._get_user(data, member.guild.id, member.id)
        entry["xp"] += amount
        entry["voice_seconds"] = entry.get("voice_seconds", 0) + voice_seconds
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
    #  Rôles de niveau (empilés)
    # ------------------------------------------------------------------ #

    async def _sync_level_roles(self, member: discord.Member, new_level: int, settings: dict = None):
        settings = settings if settings is not None else load_json(GUILD_SETTINGS_FILE, {})
        guild_settings = settings.get(str(member.guild.id), {})
        level_role_ids = guild_settings.get("level_role_ids", {})
        if not level_role_ids:
            return

        to_add = []
        for threshold_str, role_id in level_role_ids.items():
            if new_level < int(threshold_str):
                continue
            role = member.guild.get_role(role_id)
            if role and role not in member.roles:
                to_add.append(role)

        if to_add:
            try:
                await member.add_roles(*to_add, reason="Récompense de niveau")
            except discord.Forbidden:
                pass

    # ------------------------------------------------------------------ #
    #  Classement en direct
    # ------------------------------------------------------------------ #

    async def _build_leaderboard_file(self, guild: discord.Guild, guild_data: dict) -> discord.File | None:
        ranking = sorted(guild_data.items(), key=lambda kv: total_xp(kv[1]), reverse=True)[:10]
        if not ranking:
            return None

        rows = []
        for user_id, entry in ranking:
            member = guild.get_member(int(user_id))
            name = member.display_name if member else f"Utilisateur {user_id}"
            avatar_img = None
            if member:
                try:
                    avatar_bytes = await member.display_avatar.replace(size=128, format="png").read()
                    avatar_img = _make_circle_avatar(avatar_bytes, AVATAR_SIZE)
                except (discord.HTTPException, OSError):
                    avatar_img = None
            rows.append(
                (name, entry["level"], entry["xp"], xp_needed(entry["level"]), entry.get("voice_seconds", 0) / 3600, avatar_img)
            )

        buffer = await asyncio.to_thread(_render_leaderboard_png, guild.name, rows)
        return discord.File(buffer, filename="classement.png")

    async def _build_leaderboard_payload(self, guild: discord.Guild, guild_data: dict):
        file = await self._build_leaderboard_file(guild, guild_data)
        embed = discord.Embed(color=discord.Color(COLORS["gold"]))
        embed.timestamp = discord.utils.utcnow()
        embed.set_footer(text="Dernière mise à jour")
        if file:
            embed.set_image(url=f"attachment://{file.filename}")
        else:
            embed.description = "Personne n'a encore d'XP sur ce serveur."
        return embed, file

    async def _refresh_leaderboard_for_guild(self, guild: discord.Guild, settings: dict):
        guild_settings = settings.get(str(guild.id), {})
        channel_id = guild_settings.get("leaderboard_channel_id")
        if channel_id is None:
            return
        channel = guild.get_channel(channel_id)
        if channel is None:
            return

        data = load_json(LEVELS_DATA_FILE, {})
        guild_data = data.get(str(guild.id), {})
        embed, file = await self._build_leaderboard_payload(guild, guild_data)

        message = None
        message_id = guild_settings.get("leaderboard_message_id")
        if message_id:
            try:
                message = await channel.fetch_message(message_id)
            except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                message = None

        if message:
            try:
                await message.edit(embed=embed, attachments=[file] if file else [])
                return
            except discord.HTTPException:
                pass

        try:
            new_message = await channel.send(embed=embed, file=file) if file else await channel.send(embed=embed)
        except discord.HTTPException:
            return

        guild_settings["leaderboard_message_id"] = new_message.id
        settings[str(guild.id)] = guild_settings
        save_json(GUILD_SETTINGS_FILE, settings)

    @tasks.loop(seconds=LEADERBOARD_REFRESH_SECONDS)
    async def leaderboard_refresh(self):
        settings = load_json(GUILD_SETTINGS_FILE, {})
        for guild in self.bot.guilds:
            if settings.get(str(guild.id), {}).get("leaderboard_channel_id"):
                await self._refresh_leaderboard_for_guild(guild, settings)

    @leaderboard_refresh.before_loop
    async def before_leaderboard_refresh(self):
        await self.bot.wait_until_ready()

    # ------------------------------------------------------------------ #
    #  Setup
    # ------------------------------------------------------------------ #

    @app_commands.command(
        name="setup-niveaux",
        description="Crée le salon d'annonce, le classement en direct et les rôles automatiques par niveau",
    )
    @app_commands.checks.has_permissions(administrator=True)
    async def setup_niveaux(self, interaction: discord.Interaction):
        await interaction.response.defer(thinking=True, ephemeral=True)
        guild = interaction.guild
        report = []

        # 0. catégorie qui regroupe les salons de niveaux
        category = discord.utils.get(guild.categories, name=LEVELS_CATEGORY_NAME)
        try:
            if category is None:
                category = await guild.create_category(LEVELS_CATEGORY_NAME, reason="Configuration niveaux (Saphir)")
                report.append(f"✅ Catégorie créée : {LEVELS_CATEGORY_NAME}")
            else:
                report.append(f"= Catégorie déjà présente : {LEVELS_CATEGORY_NAME}")
        except discord.Forbidden:
            await interaction.followup.send("❌ Permissions insuffisantes pour créer la catégorie.", ephemeral=True)
            return

        # 1. salon d'annonce des passages de niveau
        announce_channel = discord.utils.get(guild.text_channels, name=LEVEL_UP_CHANNEL_NAME)
        try:
            if announce_channel is None:
                announce_channel = await guild.create_text_channel(
                    LEVEL_UP_CHANNEL_NAME, category=category, reason="Configuration niveaux (Saphir)"
                )
                report.append(f"✅ Salon d'annonce créé : {announce_channel.mention}")
            else:
                if announce_channel.category != category:
                    await announce_channel.edit(category=category, reason="Configuration niveaux (Saphir)")
                report.append(f"= Salon d'annonce déjà présent : {announce_channel.mention}")
        except discord.Forbidden:
            await interaction.followup.send("❌ Permissions insuffisantes pour créer le salon d'annonce.", ephemeral=True)
            return

        # 2. rôles automatiques par niveau
        settings = load_json(GUILD_SETTINGS_FILE, {})
        guild_settings = settings.setdefault(str(guild.id), {})
        level_role_ids = guild_settings.setdefault("level_role_ids", {})

        for threshold, name, color in LEVEL_ROLES:
            role = guild.get_role(level_role_ids.get(str(threshold), 0))
            if role is None:
                role = discord.utils.get(guild.roles, name=name)
            try:
                if role is None:
                    role = await guild.create_role(
                        name=name, color=discord.Color(color), hoist=True, mentionable=False,
                        reason="Récompense de niveau (Saphir)",
                    )
                    report.append(f"✅ Rôle créé : {name} (niveau {threshold})")
                else:
                    report.append(f"= Rôle déjà présent : {name} (niveau {threshold})")
                level_role_ids[str(threshold)] = role.id
            except discord.Forbidden:
                report.append(f"❌ Rôle refusé (permissions) : {name}")

        # 3. salon de classement en direct
        lb_channel = guild.get_channel(guild_settings.get("leaderboard_channel_id", 0))
        if lb_channel is None:
            lb_channel = discord.utils.get(guild.text_channels, name=LEADERBOARD_CHANNEL_NAME)
        try:
            if lb_channel is None:
                lb_channel = await guild.create_text_channel(
                    LEADERBOARD_CHANNEL_NAME, category=category, reason="Configuration niveaux (Saphir)"
                )
                report.append(f"✅ Salon classement créé : {lb_channel.mention}")
            else:
                if lb_channel.category != category:
                    await lb_channel.edit(category=category, reason="Configuration niveaux (Saphir)")
                report.append(f"= Salon classement déjà présent : {lb_channel.mention}")
            guild_settings["leaderboard_channel_id"] = lb_channel.id
        except discord.Forbidden:
            report.append(f"❌ Salon classement refusé (permissions) : {LEADERBOARD_CHANNEL_NAME}")

        save_json(GUILD_SETTINGS_FILE, settings)
        await self._refresh_leaderboard_for_guild(guild, settings)

        embed = discord.Embed(
            title="🎉 Configuration des niveaux",
            description="\n".join(report),
            color=discord.Color(COLORS["saphir"]),
        )
        await interaction.followup.send(embed=embed, ephemeral=True)

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
            await self._sync_level_roles(message.author, leveled_to)

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
                    leveled_to = self._apply_xp(
                        data, member, random.randint(VOICE_XP_MIN, VOICE_XP_MAX), voice_seconds=VOICE_TICK_SECONDS
                    )
                    if leveled_to:
                        level_ups.append((member, leveled_to))

        if changed:
            save_json(LEVELS_DATA_FILE, data)

        if level_ups:
            settings = load_json(GUILD_SETTINGS_FILE, {})
            for member, level in level_ups:
                await self._announce_level_up(member, level, None)
                await self._sync_level_roles(member, level, settings)

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
        embed.add_field(name="Temps en vocal", value=f"{entry.get('voice_seconds', 0) / 3600:.1f} h")
        embed.set_thumbnail(url=membre.display_avatar.url)
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="classement", description="Classement des membres par XP sur ce serveur")
    async def classement(self, interaction: discord.Interaction):
        await interaction.response.defer(thinking=True)
        data = load_json(LEVELS_DATA_FILE, {})
        guild_data = data.get(str(interaction.guild.id), {})
        embed, file = await self._build_leaderboard_payload(interaction.guild, guild_data)
        if file:
            await interaction.followup.send(embed=embed, file=file)
        else:
            await interaction.followup.send(embed=embed)


async def setup(bot):
    await bot.add_cog(Leveling(bot))
