import datetime

import discord
from discord import app_commands
from discord.ext import commands

from config import COLORS, LOG_CHANNELS, LOGS_CATEGORY_NAME


def _trim(text: str, limit: int = 1000) -> str:
    if text is None:
        return "*(vide)*"
    text = text if isinstance(text, str) else str(text)
    return text if len(text) <= limit else text[: limit - 1] + "…"


class Logs(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    # ------------------------------------------------------------------ #
    #  Setup
    # ------------------------------------------------------------------ #

    @app_commands.command(
        name="setup-logs",
        description="Crée (ou met à jour) la catégorie de logs et tous ses salons, invisibles pour les membres",
    )
    @app_commands.checks.has_permissions(administrator=True)
    async def setup_logs(self, interaction: discord.Interaction):
        await interaction.response.defer(thinking=True, ephemeral=True)
        guild = interaction.guild
        report = []

        overwrites = {guild.default_role: discord.PermissionOverwrite(view_channel=False)}

        category = discord.utils.get(guild.categories, name=LOGS_CATEGORY_NAME)
        try:
            if category is None:
                category = await guild.create_category(
                    LOGS_CATEGORY_NAME, overwrites=overwrites, reason="Configuration des logs (Saphir)"
                )
                report.append(f"✅ Catégorie créée : {LOGS_CATEGORY_NAME}")
            else:
                await category.edit(overwrites=overwrites, reason="Configuration des logs (Saphir)")
                report.append(f"🔄 Catégorie mise à jour : {LOGS_CATEGORY_NAME}")
        except discord.Forbidden:
            await interaction.followup.send("❌ Permissions insuffisantes pour créer la catégorie.", ephemeral=True)
            return

        for channel_name in LOG_CHANNELS.values():
            channel = discord.utils.get(category.channels, name=channel_name)
            try:
                if channel is None:
                    await guild.create_text_channel(
                        channel_name, category=category, overwrites=overwrites, reason="Configuration des logs (Saphir)"
                    )
                    report.append(f"✅ Salon créé : {channel_name}")
                else:
                    await channel.edit(overwrites=overwrites, reason="Configuration des logs (Saphir)")
                    report.append(f"🔄 Salon mis à jour : {channel_name}")
            except discord.Forbidden:
                report.append(f"❌ Salon refusé (permissions) : {channel_name}")

        embed = discord.Embed(
            title="📋 Configuration des logs",
            description="\n".join(report),
            color=discord.Color(COLORS["saphir"]),
        )
        await interaction.followup.send(embed=embed, ephemeral=True)

    @setup_logs.error
    async def setup_logs_error(self, interaction: discord.Interaction, error: app_commands.AppCommandError):
        if isinstance(error, app_commands.MissingPermissions):
            await interaction.response.send_message("Seul un administrateur peut utiliser cette commande.", ephemeral=True)

    # ------------------------------------------------------------------ #
    #  Helpers
    # ------------------------------------------------------------------ #

    async def _log(self, guild: discord.Guild, key: str, embed: discord.Embed):
        channel = discord.utils.get(guild.text_channels, name=LOG_CHANNELS[key])
        if channel:
            try:
                await channel.send(embed=embed)
            except discord.HTTPException:
                pass

    async def _find_audit_entry(self, guild: discord.Guild, action, target_id=None, within_seconds=5):
        try:
            async for entry in guild.audit_logs(limit=5, action=action):
                if target_id is not None and getattr(entry.target, "id", None) != target_id:
                    continue
                age = (discord.utils.utcnow() - entry.created_at).total_seconds()
                if 0 <= age <= within_seconds:
                    return entry
                return None
        except discord.Forbidden:
            return None
        return None

    # ------------------------------------------------------------------ #
    #  Arrivées / départs / modération
    # ------------------------------------------------------------------ #

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        age = discord.utils.utcnow() - member.created_at
        embed = discord.Embed(
            title="📥 Arrivée",
            description=f"{member.mention} ({member})",
            color=discord.Color(COLORS["success"]),
        )
        embed.add_field(name="Compte créé", value=f"{discord.utils.format_dt(member.created_at, style='R')}")
        if age.days < 7:
            embed.add_field(name="⚠️", value="Compte créé il y a moins de 7 jours")
        embed.set_thumbnail(url=member.display_avatar.url)
        embed.set_footer(text=f"ID : {member.id}")
        await self._log(member.guild, "join_leave", embed)

    @commands.Cog.listener()
    async def on_member_remove(self, member: discord.Member):
        guild = member.guild

        kick_entry = await self._find_audit_entry(guild, discord.AuditLogAction.kick, target_id=member.id)
        if kick_entry:
            embed = discord.Embed(
                title="🥾 Expulsion (kick)",
                description=f"{member.mention} ({member})",
                color=discord.Color(COLORS["danger"]),
            )
            embed.add_field(name="Modérateur", value=kick_entry.user.mention if kick_entry.user else "Inconnu")
            embed.add_field(name="Raison", value=kick_entry.reason or "Non spécifiée", inline=False)
            embed.set_footer(text=f"ID : {member.id}")
            await self._log(guild, "moderation", embed)
            return

        roles = [r.mention for r in member.roles if not r.is_default()]
        embed = discord.Embed(
            title="📤 Départ",
            description=f"{member.mention} ({member})",
            color=discord.Color(COLORS["grey"]),
        )
        embed.add_field(name="Arrivé", value=discord.utils.format_dt(member.joined_at, style="R") if member.joined_at else "Inconnu")
        embed.add_field(name="Rôles qu'il avait", value=", ".join(roles) if roles else "Aucun", inline=False)
        embed.set_footer(text=f"ID : {member.id}")
        await self._log(guild, "join_leave", embed)

    @commands.Cog.listener()
    async def on_member_ban(self, guild: discord.Guild, user: discord.User):
        entry = await self._find_audit_entry(guild, discord.AuditLogAction.ban, target_id=user.id)
        embed = discord.Embed(
            title="🔨 Bannissement",
            description=f"{user.mention} ({user})",
            color=discord.Color(COLORS["danger"]),
        )
        if entry:
            embed.add_field(name="Modérateur", value=entry.user.mention if entry.user else "Inconnu")
            embed.add_field(name="Raison", value=entry.reason or "Non spécifiée", inline=False)
        embed.set_footer(text=f"ID : {user.id}")
        await self._log(guild, "moderation", embed)

    @commands.Cog.listener()
    async def on_member_unban(self, guild: discord.Guild, user: discord.User):
        entry = await self._find_audit_entry(guild, discord.AuditLogAction.unban, target_id=user.id)
        embed = discord.Embed(
            title="🔓 Débannissement",
            description=f"{user.mention} ({user})",
            color=discord.Color(COLORS["success"]),
        )
        if entry:
            embed.add_field(name="Modérateur", value=entry.user.mention if entry.user else "Inconnu")
        embed.set_footer(text=f"ID : {user.id}")
        await self._log(guild, "moderation", embed)

    # ------------------------------------------------------------------ #
    #  Pseudos / avatars / rôles d'un membre
    # ------------------------------------------------------------------ #

    @commands.Cog.listener()
    async def on_member_update(self, before: discord.Member, after: discord.Member):
        guild = after.guild

        if before.nick != after.nick:
            embed = discord.Embed(title="✏️ Pseudo modifié", description=after.mention, color=discord.Color(COLORS["gold"]))
            embed.add_field(name="Avant", value=before.nick or "*(aucun)*")
            embed.add_field(name="Après", value=after.nick or "*(aucun)*")
            embed.set_footer(text=f"ID : {after.id}")
            await self._log(guild, "profile", embed)

        if before.roles != after.roles:
            added = [r.mention for r in after.roles if r not in before.roles]
            removed = [r.mention for r in before.roles if r not in after.roles]
            if added or removed:
                embed = discord.Embed(title="🎭 Rôles modifiés", description=after.mention, color=discord.Color(COLORS["gold"]))
                if added:
                    embed.add_field(name="➕ Ajoutés", value=", ".join(added), inline=False)
                if removed:
                    embed.add_field(name="➖ Retirés", value=", ".join(removed), inline=False)
                embed.set_footer(text=f"ID : {after.id}")
                await self._log(guild, "roles", embed)

        if before.timed_out_until != after.timed_out_until and after.timed_out_until:
            embed = discord.Embed(
                title="🔇 Mise en sourdine (timeout)",
                description=after.mention,
                color=discord.Color(COLORS["danger"]),
            )
            embed.add_field(name="Jusqu'à", value=discord.utils.format_dt(after.timed_out_until, style="F"))
            embed.set_footer(text=f"ID : {after.id}")
            await self._log(guild, "moderation", embed)

    @commands.Cog.listener()
    async def on_user_update(self, before: discord.User, after: discord.User):
        if before.name == after.name and before.display_avatar.key == after.display_avatar.key:
            return

        for guild in self.bot.guilds:
            member = guild.get_member(after.id)
            if member is None:
                continue

            if before.name != after.name:
                embed = discord.Embed(title="🏷️ Nom d'utilisateur modifié", description=member.mention, color=discord.Color(COLORS["gold"]))
                embed.add_field(name="Avant", value=before.name)
                embed.add_field(name="Après", value=after.name)
                embed.set_footer(text=f"ID : {after.id}")
                await self._log(guild, "profile", embed)

            if before.display_avatar.key != after.display_avatar.key:
                embed = discord.Embed(title="🖼️ Avatar modifié", description=member.mention, color=discord.Color(COLORS["gold"]))
                embed.set_thumbnail(url=after.display_avatar.url)
                embed.set_footer(text=f"ID : {after.id}")
                await self._log(guild, "profile", embed)

    # ------------------------------------------------------------------ #
    #  Messages
    # ------------------------------------------------------------------ #

    @commands.Cog.listener()
    async def on_message_delete(self, message: discord.Message):
        if not message.guild or message.author.bot:
            return
        embed = discord.Embed(
            title="🗑️ Message supprimé",
            description=f"Auteur : {message.author.mention}\nSalon : {message.channel.mention}",
            color=discord.Color(COLORS["danger"]),
        )
        embed.add_field(name="Contenu", value=_trim(message.content) or "*(vide)*", inline=False)
        if message.attachments:
            embed.add_field(name="Pièces jointes", value=str(len(message.attachments)))
        embed.set_footer(text=f"ID auteur : {message.author.id}")
        await self._log(message.guild, "messages", embed)

    @commands.Cog.listener()
    async def on_message_edit(self, before: discord.Message, after: discord.Message):
        if not before.guild or before.author.bot or before.content == after.content:
            return
        embed = discord.Embed(
            title="✏️ Message modifié",
            description=f"Auteur : {before.author.mention}\nSalon : {before.channel.mention} · [Aller au message]({after.jump_url})",
            color=discord.Color(COLORS["gold"]),
        )
        embed.add_field(name="Avant", value=_trim(before.content), inline=False)
        embed.add_field(name="Après", value=_trim(after.content), inline=False)
        embed.set_footer(text=f"ID auteur : {before.author.id}")
        await self._log(before.guild, "messages", embed)

    # ------------------------------------------------------------------ #
    #  Salons
    # ------------------------------------------------------------------ #

    @commands.Cog.listener()
    async def on_guild_channel_create(self, channel: discord.abc.GuildChannel):
        embed = discord.Embed(
            title="📁 Salon créé",
            description=f"**{channel.name}** ({channel.type.name})",
            color=discord.Color(COLORS["success"]),
        )
        embed.set_footer(text=f"ID : {channel.id}")
        await self._log(channel.guild, "channels", embed)

    @commands.Cog.listener()
    async def on_guild_channel_delete(self, channel: discord.abc.GuildChannel):
        entry = await self._find_audit_entry(channel.guild, discord.AuditLogAction.channel_delete, target_id=channel.id)
        embed = discord.Embed(
            title="📁 Salon supprimé",
            description=f"**{channel.name}** ({channel.type.name})",
            color=discord.Color(COLORS["danger"]),
        )
        if entry and entry.user:
            embed.add_field(name="Par", value=entry.user.mention)
        embed.set_footer(text=f"ID : {channel.id}")
        await self._log(channel.guild, "channels", embed)

    @commands.Cog.listener()
    async def on_guild_channel_update(self, before: discord.abc.GuildChannel, after: discord.abc.GuildChannel):
        if before.name == after.name:
            return
        embed = discord.Embed(
            title="📁 Salon renommé",
            description=f"{after.mention if hasattr(after, 'mention') else after.name}",
            color=discord.Color(COLORS["gold"]),
        )
        embed.add_field(name="Avant", value=before.name)
        embed.add_field(name="Après", value=after.name)
        embed.set_footer(text=f"ID : {after.id}")
        await self._log(after.guild, "channels", embed)

    # ------------------------------------------------------------------ #
    #  Rôles (création / suppression)
    # ------------------------------------------------------------------ #

    @commands.Cog.listener()
    async def on_guild_role_create(self, role: discord.Role):
        embed = discord.Embed(
            title="🎭 Rôle créé",
            description=role.mention,
            color=discord.Color(COLORS["success"]),
        )
        embed.set_footer(text=f"ID : {role.id}")
        await self._log(role.guild, "roles", embed)

    @commands.Cog.listener()
    async def on_guild_role_delete(self, role: discord.Role):
        entry = await self._find_audit_entry(role.guild, discord.AuditLogAction.role_delete, target_id=role.id)
        embed = discord.Embed(
            title="🎭 Rôle supprimé",
            description=f"**{role.name}**",
            color=discord.Color(COLORS["danger"]),
        )
        if entry and entry.user:
            embed.add_field(name="Par", value=entry.user.mention)
        embed.set_footer(text=f"ID : {role.id}")
        await self._log(role.guild, "roles", embed)

    # ------------------------------------------------------------------ #
    #  Serveur
    # ------------------------------------------------------------------ #

    @commands.Cog.listener()
    async def on_guild_update(self, before: discord.Guild, after: discord.Guild):
        changes = []
        if before.name != after.name:
            changes.append(f"**Nom** : {before.name} → {after.name}")
        if before.icon != after.icon:
            changes.append("**Icône** modifiée")
        if before.owner_id != after.owner_id:
            changes.append(f"**Propriétaire** : <@{before.owner_id}> → <@{after.owner_id}>")
        if not changes:
            return
        embed = discord.Embed(
            title="⚙️ Serveur modifié",
            description="\n".join(changes),
            color=discord.Color(COLORS["gold"]),
        )
        await self._log(after, "server", embed)

    # ------------------------------------------------------------------ #
    #  Vocal (au pixel près)
    # ------------------------------------------------------------------ #

    @commands.Cog.listener()
    async def on_voice_state_update(
        self, member: discord.Member, before: discord.VoiceState, after: discord.VoiceState
    ):
        guild = member.guild

        if before.channel != after.channel:
            if before.channel is None:
                embed = discord.Embed(
                    title="🎙️ Connexion vocale",
                    description=f"{member.mention} a rejoint {after.channel.mention}",
                    color=discord.Color(COLORS["success"]),
                )
            elif after.channel is None:
                embed = discord.Embed(
                    title="🎙️ Déconnexion vocale",
                    description=f"{member.mention} a quitté {before.channel.mention}",
                    color=discord.Color(COLORS["grey"]),
                )
            else:
                embed = discord.Embed(
                    title="🎙️ Changement de salon vocal",
                    description=f"{member.mention} : {before.channel.mention} → {after.channel.mention}",
                    color=discord.Color(COLORS["gold"]),
                )
            embed.set_footer(text=f"ID : {member.id}")
            await self._log(guild, "voice", embed)

        toggles = [
            ("self_mute", "🎤 s'est mis en sourdine", "🎤 n'est plus en sourdine (perso)"),
            ("self_deaf", "🔇 s'est rendu sourd", "🔇 n'est plus sourd (perso)"),
            ("mute", "🔇 a été rendu muet par le serveur", "🔊 n'est plus muet (serveur)"),
            ("deaf", "🔇 a été rendu sourd par le serveur", "🔊 n'est plus sourd (serveur)"),
            ("self_stream", "🖥️ a commencé à partager son écran", "🖥️ a arrêté son partage d'écran"),
            ("self_video", "🎥 a activé sa caméra", "🎥 a désactivé sa caméra"),
        ]
        for attr, on_text, off_text in toggles:
            before_val = getattr(before, attr)
            after_val = getattr(after, attr)
            if before_val == after_val:
                continue
            embed = discord.Embed(
                title="🎙️ Vocal",
                description=f"{member.mention} {on_text if after_val else off_text}",
                color=discord.Color(COLORS["grey"]),
            )
            embed.set_footer(text=f"ID : {member.id}")
            await self._log(guild, "voice", embed)


async def setup(bot):
    await bot.add_cog(Logs(bot))
