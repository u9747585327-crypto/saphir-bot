import datetime
import re

import discord
from discord import app_commands
from discord.ext import commands, tasks

from config import (
    COLORS,
    EXILE_ROLE_NAME,
    PRISON_CATEGORY_NAME,
    PRISON_DATA_FILE,
    PRISON_TEXT_CHANNEL,
    PRISON_VOICE_CHANNEL,
)
from storage import load_json, save_json

DURATION_RE = re.compile(r"^(\d+)\s*([smhdw])$", re.IGNORECASE)
UNIT_SECONDS = {"s": 1, "m": 60, "h": 3600, "d": 86400, "w": 604800}


def parse_duration(text: str) -> datetime.timedelta:
    match = DURATION_RE.match(text.strip().lower())
    if not match:
        raise ValueError("Format de durée invalide. Exemples valides : 30s, 10m, 2h, 1d, 1w.")
    amount = int(match.group(1))
    unit = match.group(2)
    return datetime.timedelta(seconds=amount * UNIT_SECONDS[unit])


class Prison(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.check_releases.start()

    def cog_unload(self):
        self.check_releases.cancel()

    # ------------------------------------------------------------------ #
    #  Setup
    # ------------------------------------------------------------------ #

    @app_commands.command(
        name="setup-prison",
        description="Crée (ou met à jour) la catégorie Alcatraz, ses salons et le rôle Exilé",
    )
    @app_commands.checks.has_permissions(administrator=True)
    async def setup_prison(self, interaction: discord.Interaction):
        guild = interaction.guild
        report = []

        exile_role = discord.utils.get(guild.roles, name=EXILE_ROLE_NAME)
        try:
            if exile_role is None:
                exile_role = await guild.create_role(
                    name=EXILE_ROLE_NAME,
                    color=discord.Color(COLORS["danger"]),
                    hoist=True,
                    mentionable=False,
                    reason="Configuration de la prison (Saphir)",
                )
                report.append(f"✅ Rôle créé : {EXILE_ROLE_NAME}")
            else:
                report.append(f"= Rôle déjà présent : {EXILE_ROLE_NAME}")
        except discord.Forbidden:
            await interaction.response.send_message("❌ Permissions insuffisantes pour créer le rôle Exilé.", ephemeral=True)
            return

        overwrites = {
            guild.default_role: discord.PermissionOverwrite(view_channel=False),
            exile_role: discord.PermissionOverwrite(
                view_channel=True,
                send_messages=True,
                read_message_history=True,
                connect=True,
                speak=True,
            ),
        }

        category = discord.utils.get(guild.categories, name=PRISON_CATEGORY_NAME)
        try:
            if category is None:
                category = await guild.create_category(
                    PRISON_CATEGORY_NAME, overwrites=overwrites, reason="Configuration de la prison (Saphir)"
                )
                report.append(f"✅ Catégorie créée : {PRISON_CATEGORY_NAME}")
            else:
                await category.edit(overwrites=overwrites, reason="Configuration de la prison (Saphir)")
                report.append(f"🔄 Catégorie mise à jour : {PRISON_CATEGORY_NAME}")
        except discord.Forbidden:
            await interaction.response.send_message("❌ Permissions insuffisantes pour créer la catégorie.", ephemeral=True)
            return

        text_channel = discord.utils.get(category.channels, name=PRISON_TEXT_CHANNEL)
        try:
            if text_channel is None:
                await guild.create_text_channel(
                    PRISON_TEXT_CHANNEL, category=category, overwrites=overwrites, reason="Configuration de la prison (Saphir)"
                )
                report.append(f"✅ Salon texte créé : {PRISON_TEXT_CHANNEL}")
            else:
                await text_channel.edit(overwrites=overwrites, reason="Configuration de la prison (Saphir)")
                report.append(f"🔄 Salon texte mis à jour : {PRISON_TEXT_CHANNEL}")
        except discord.Forbidden:
            report.append(f"❌ Salon texte refusé (permissions) : {PRISON_TEXT_CHANNEL}")

        voice_channel = discord.utils.get(category.channels, name=PRISON_VOICE_CHANNEL)
        try:
            if voice_channel is None:
                await guild.create_voice_channel(
                    PRISON_VOICE_CHANNEL, category=category, overwrites=overwrites, reason="Configuration de la prison (Saphir)"
                )
                report.append(f"✅ Salon vocal créé : {PRISON_VOICE_CHANNEL}")
            else:
                await voice_channel.edit(overwrites=overwrites, reason="Configuration de la prison (Saphir)")
                report.append(f"🔄 Salon vocal mis à jour : {PRISON_VOICE_CHANNEL}")
        except discord.Forbidden:
            report.append(f"❌ Salon vocal refusé (permissions) : {PRISON_VOICE_CHANNEL}")

        embed = discord.Embed(
            title="🔒 Configuration de la prison",
            description="\n".join(report),
            color=discord.Color(COLORS["danger"]),
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    # ------------------------------------------------------------------ #
    #  Jail / Unjail
    # ------------------------------------------------------------------ #

    async def _announce(self, guild: discord.Guild, embed: discord.Embed):
        channel = discord.utils.get(guild.text_channels, name=PRISON_TEXT_CHANNEL)
        if channel:
            try:
                await channel.send(embed=embed)
            except discord.HTTPException:
                pass

    @app_commands.command(name="jail", description="Envoie un membre à Alcatraz pour une durée donnée, en lui retirant ses rôles")
    @app_commands.describe(
        membre="Membre à emprisonner",
        duree="Durée de la peine, ex : 30s, 10m, 2h, 1d, 1w",
        raison="Raison de l'emprisonnement",
    )
    @app_commands.checks.has_permissions(moderate_members=True)
    async def jail(
        self,
        interaction: discord.Interaction,
        membre: discord.Member,
        duree: str,
        raison: str = "Non spécifiée",
    ):
        guild = interaction.guild

        try:
            delta = parse_duration(duree)
        except ValueError as e:
            await interaction.response.send_message(f"❌ {e}", ephemeral=True)
            return

        exile_role = discord.utils.get(guild.roles, name=EXILE_ROLE_NAME)
        if exile_role is None:
            await interaction.response.send_message("Le rôle Exilé n'existe pas. Lance `/setup-prison` d'abord.", ephemeral=True)
            return

        if exile_role in membre.roles:
            await interaction.response.send_message(f"{membre.mention} est déjà à Alcatraz. Utilise `/unjail` d'abord si besoin.", ephemeral=True)
            return

        await interaction.response.defer(thinking=True, ephemeral=True)

        removable_roles = [r for r in membre.roles if not r.is_default() and not r.managed]
        unjail_at = datetime.datetime.now(datetime.timezone.utc) + delta

        data = load_json(PRISON_DATA_FILE, {})
        data.setdefault(str(guild.id), {})[str(membre.id)] = {
            "role_ids": [r.id for r in removable_roles],
            "unjail_at": unjail_at.isoformat(),
            "reason": raison,
            "moderator_id": interaction.user.id,
        }

        try:
            if removable_roles:
                await membre.remove_roles(*removable_roles, reason=f"Jail par {interaction.user} : {raison}")
            await membre.add_roles(exile_role, reason=f"Jail par {interaction.user} : {raison}")
        except discord.Forbidden:
            await interaction.followup.send("❌ Permissions insuffisantes (rôle du bot trop bas par rapport à ce membre ?).", ephemeral=True)
            return

        save_json(PRISON_DATA_FILE, data)

        embed = discord.Embed(
            title="⛓️ Membre envoyé à Alcatraz",
            color=discord.Color(COLORS["danger"]),
        )
        embed.add_field(name="Membre", value=membre.mention, inline=False)
        embed.add_field(name="Durée", value=duree)
        embed.add_field(name="Libération", value=discord.utils.format_dt(unjail_at, style="R"))
        embed.add_field(name="Raison", value=raison, inline=False)
        embed.add_field(name="Modérateur", value=interaction.user.mention, inline=False)

        await interaction.followup.send(embed=embed, ephemeral=True)
        await self._announce(guild, embed)

        try:
            await membre.send(
                f"⛓️ Tu as été envoyé à Alcatraz sur **{guild.name}** pour {duree} (raison : {raison}). "
                f"Tu retrouveras tes rôles automatiquement à ta libération."
            )
        except discord.HTTPException:
            pass

    async def _release(self, guild: discord.Guild, user_id: str, entry: dict, reason: str):
        exile_role = discord.utils.get(guild.roles, name=EXILE_ROLE_NAME)
        member = guild.get_member(int(user_id))

        if member is not None:
            try:
                if exile_role and exile_role in member.roles:
                    await member.remove_roles(exile_role, reason=reason)
            except discord.Forbidden:
                pass

            roles_to_restore = [guild.get_role(rid) for rid in entry.get("role_ids", [])]
            roles_to_restore = [r for r in roles_to_restore if r is not None]
            try:
                if roles_to_restore:
                    await member.add_roles(*roles_to_restore, reason=reason)
            except discord.Forbidden:
                pass

            embed = discord.Embed(
                title="🔓 Libération d'Alcatraz",
                description=f"{member.mention} a purgé sa peine et retrouve ses rôles.",
                color=discord.Color(COLORS["saphir"]),
            )
            await self._announce(guild, embed)

    @app_commands.command(name="unjail", description="Libère immédiatement un membre d'Alcatraz et lui rend ses rôles")
    @app_commands.describe(membre="Membre à libérer")
    @app_commands.checks.has_permissions(moderate_members=True)
    async def unjail(self, interaction: discord.Interaction, membre: discord.Member):
        guild = interaction.guild
        data = load_json(PRISON_DATA_FILE, {})
        guild_data = data.get(str(guild.id), {})
        entry = guild_data.pop(str(membre.id), None)

        if entry is None:
            await interaction.response.send_message(f"{membre.mention} n'est pas à Alcatraz.", ephemeral=True)
            return

        await interaction.response.defer(thinking=True, ephemeral=True)
        await self._release(guild, str(membre.id), entry, reason=f"Libéré manuellement par {interaction.user}")
        save_json(PRISON_DATA_FILE, data)

        await interaction.followup.send(f"🔓 {membre.mention} a été libéré d'Alcatraz.", ephemeral=True)

    @setup_prison.error
    @jail.error
    @unjail.error
    async def prison_error(self, interaction: discord.Interaction, error: app_commands.AppCommandError):
        if isinstance(error, app_commands.MissingPermissions):
            await interaction.response.send_message("Tu n'as pas la permission de faire ça.", ephemeral=True)

    # ------------------------------------------------------------------ #
    #  Libération automatique
    # ------------------------------------------------------------------ #

    @tasks.loop(seconds=30)
    async def check_releases(self):
        data = load_json(PRISON_DATA_FILE, {})
        now = datetime.datetime.now(datetime.timezone.utc)
        changed = False

        for guild_id, guild_data in list(data.items()):
            guild = self.bot.get_guild(int(guild_id))
            for user_id, entry in list(guild_data.items()):
                unjail_at = datetime.datetime.fromisoformat(entry["unjail_at"])
                if now < unjail_at:
                    continue

                if guild is not None:
                    await self._release(guild, user_id, entry, reason="Fin de la peine à Alcatraz")

                del guild_data[user_id]
                changed = True

            if not guild_data:
                del data[guild_id]

        if changed:
            save_json(PRISON_DATA_FILE, data)

    @check_releases.before_loop
    async def before_check_releases(self):
        await self.bot.wait_until_ready()


async def setup(bot):
    await bot.add_cog(Prison(bot))
