import time
from collections import defaultdict, deque

import discord
from discord import app_commands
from discord.ext import commands

from cogs._shared import handle_app_error
from config import (
    ANTIRAID_JOIN_COUNT,
    ANTIRAID_JOIN_WINDOW,
    ANTIRAID_MIN_ACCOUNT_AGE_DAYS,
    ANTIRAID_MODE_DURATION,
    COLORS,
    GUILD_SETTINGS_FILE,
    LOG_CHANNELS,
)
from storage import aload_json, asave_json


class AntiRaid(commands.Cog):
    """Détecte les vagues d'arrivées (join flood) typiques d'un raid et ALERTE le staff —
    sans jamais expulser automatiquement, pour que les vrais nouveaux comptes puissent
    rejoindre. Le staff décide : /lockdown ferme le serveur (toute nouvelle arrivée
    expulsée) jusqu'à /unlockdown.

    Réglages par serveur dans guild_settings : `antiraid_enabled` (défaut True) et
    `antiraid_lockdown` (défaut False). Ils sont mis en cache mémoire pour ne pas relire le
    fichier à chaque arrivée (précisément quand elles pleuvent, pendant un raid)."""

    def __init__(self, bot):
        self.bot = bot
        self.recent_joins = defaultdict(deque)   # guild_id -> timestamps des arrivées récentes
        self.raid_until = defaultdict(float)     # guild_id -> instant de fin du mode raid
        self._cache = {}                         # guild_id -> {"enabled": bool, "lockdown": bool}

    async def _conf(self, guild_id: int) -> dict:
        if guild_id not in self._cache:
            settings = await aload_json(GUILD_SETTINGS_FILE, {})
            gs = settings.get(str(guild_id), {})
            self._cache[guild_id] = {
                "enabled": gs.get("antiraid_enabled", True),
                "lockdown": gs.get("antiraid_lockdown", False),
            }
        return self._cache[guild_id]

    async def _save_conf(self, guild_id: int, **changes):
        conf = await self._conf(guild_id)
        conf.update(changes)
        settings = await aload_json(GUILD_SETTINGS_FILE, {})
        gs = settings.setdefault(str(guild_id), {})
        gs["antiraid_enabled"] = conf["enabled"]
        gs["antiraid_lockdown"] = conf["lockdown"]
        await asave_json(GUILD_SETTINGS_FILE, settings)

    def _mod_log(self, guild: discord.Guild):
        return discord.utils.get(guild.text_channels, name=LOG_CHANNELS["moderation"])

    async def _alert(self, guild: discord.Guild, title: str, description: str, color_key: str = "danger"):
        channel = self._mod_log(guild)
        if channel is None:
            return
        embed = discord.Embed(title=title, description=description, color=discord.Color(COLORS[color_key]))
        embed.timestamp = discord.utils.utcnow()
        try:
            await channel.send(embed=embed)
        except discord.HTTPException:
            pass

    def _too_young(self, member: discord.Member) -> bool:
        age = discord.utils.utcnow() - member.created_at
        return age.days < ANTIRAID_MIN_ACCOUNT_AGE_DAYS

    async def _remove(self, member: discord.Member, reason: str) -> bool:
        try:
            await member.kick(reason=reason)
            return True
        except discord.HTTPException:
            return False

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        if member.bot:
            return
        guild = member.guild
        conf = await self._conf(guild.id)

        # lockdown manuel : on expulse toute arrivée, sans condition
        if conf["lockdown"]:
            if await self._remove(member, "Lockdown anti-raid (serveur fermé)"):
                await self._alert(
                    guild, "🔒 Lockdown — arrivée bloquée",
                    f"{member.mention} (`{member}`) a été expulsé : le serveur est en lockdown.",
                )
            return

        if not conf["enabled"]:
            return

        now = time.time()
        joins = self.recent_joins[guild.id]
        joins.append(now)
        while joins and now - joins[0] > ANTIRAID_JOIN_WINDOW:
            joins.popleft()

        # détection d'une vague d'arrivées : on ALERTE seulement, on n'expulse personne
        # automatiquement — les vrais nouveaux comptes doivent pouvoir rejoindre. Le staff
        # décide, et peut fermer le serveur avec /lockdown si c'est vraiment un raid.
        already_alerted = now < self.raid_until[guild.id]
        if not already_alerted and len(joins) >= ANTIRAID_JOIN_COUNT:
            self.raid_until[guild.id] = now + ANTIRAID_MODE_DURATION  # anti-spam d'alerte
            young = self._too_young(member)
            await self._alert(
                guild, "🚨 Vague d'arrivées détectée",
                f"**{len(joins)} arrivées en {ANTIRAID_JOIN_WINDOW}s.** Ça peut être un raid — "
                "ou juste une pub qui marche. **Aucune expulsion automatique.**\n"
                f"Le dernier compte arrivé est {'récent ⚠️' if young else 'ancien'}. "
                "Si c'est un raid, ferme le serveur avec `/lockdown` (puis `/unlockdown`).",
                color_key="gold",
            )

    # ------------------------------------------------------------------ #
    #  Commandes
    # ------------------------------------------------------------------ #

    @app_commands.command(name="antiraid", description="Active, désactive ou affiche l'état de l'anti-raid")
    @app_commands.describe(action="Ce que tu veux faire")
    @app_commands.choices(action=[
        app_commands.Choice(name="Activer", value="on"),
        app_commands.Choice(name="Désactiver", value="off"),
        app_commands.Choice(name="État", value="status"),
    ])
    @app_commands.checks.has_permissions(administrator=True)
    async def antiraid(self, interaction: discord.Interaction, action: app_commands.Choice[str]):
        guild = interaction.guild
        conf = await self._conf(guild.id)

        if action.value == "on":
            await self._save_conf(guild.id, enabled=True)
            msg = "✅ Anti-raid **activé**."
        elif action.value == "off":
            await self._save_conf(guild.id, enabled=False)
            msg = "⛔ Anti-raid **désactivé**."
        else:
            recent_alert = time.time() < self.raid_until[guild.id]
            msg = (
                f"**Anti-raid** : {'✅ activé' if conf['enabled'] else '⛔ désactivé'}\n"
                f"**Lockdown** : {'🔒 actif (arrivées bloquées)' if conf['lockdown'] else 'ouvert'}\n"
                f"**Alerte récente** : {'🚨 oui' if recent_alert else 'non'}\n\n"
                f"Seuil d'alerte : {ANTIRAID_JOIN_COUNT} arrivées / {ANTIRAID_JOIN_WINDOW}s.\n"
                "La détection **alerte seulement** — aucune expulsion automatique. "
                "Les nouveaux comptes peuvent rejoindre. Utilise `/lockdown` pour tout bloquer en cas de vrai raid."
            )

        embed = discord.Embed(title="🛡️ Anti-raid", description=msg, color=discord.Color(COLORS["saphir"]))
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="lockdown", description="Ferme le serveur : toute nouvelle arrivée est expulsée")
    @app_commands.checks.has_permissions(administrator=True)
    async def lockdown(self, interaction: discord.Interaction):
        await self._save_conf(interaction.guild.id, lockdown=True)
        await self._alert(
            interaction.guild, "🔒 Lockdown activé",
            f"{interaction.user.mention} a fermé le serveur. Toute nouvelle arrivée sera expulsée "
            "jusqu'à `/unlockdown`.",
            color_key="danger",
        )
        await interaction.response.send_message(
            "🔒 **Lockdown activé** — toute nouvelle arrivée est expulsée jusqu'à `/unlockdown`.",
            ephemeral=True,
        )

    @app_commands.command(name="unlockdown", description="Rouvre le serveur après un lockdown")
    @app_commands.checks.has_permissions(administrator=True)
    async def unlockdown(self, interaction: discord.Interaction):
        await self._save_conf(interaction.guild.id, lockdown=False)
        await self._alert(
            interaction.guild, "🔓 Lockdown levé",
            f"{interaction.user.mention} a rouvert le serveur.",
            color_key="success",
        )
        await interaction.response.send_message("🔓 **Serveur rouvert.**", ephemeral=True)

    @antiraid.error
    @lockdown.error
    @unlockdown.error
    async def antiraid_error(self, interaction: discord.Interaction, error: app_commands.AppCommandError):
        await handle_app_error(
            interaction, error,
            perm_message="Seul un administrateur peut gérer l'anti-raid.",
            command_label="antiraid",
        )


async def setup(bot):
    await bot.add_cog(AntiRaid(bot))
