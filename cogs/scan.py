import datetime
import os
import re

import discord
from discord import app_commands
from discord.ext import commands

from config import SCAN_DIR, COLORS
from storage import load_json, save_json


def _safe_name(name: str) -> str:
    cleaned = re.sub(r'[\\/:*?"<>|]+', "_", name).strip()
    return cleaned or "serveur"


def _serialize_overwrites(channel):
    entries = []
    for target, overwrite in channel.overwrites.items():
        allow, deny = overwrite.pair()
        entry = {"allow": allow.value, "deny": deny.value}
        if isinstance(target, discord.Role):
            entry["kind"] = "role"
            entry["name"] = "@everyone" if target.is_default() else target.name
        else:
            entry["kind"] = "member"
            entry["id"] = target.id
            entry["name"] = str(target)
        entries.append(entry)
    return entries


def _serialize_channel(channel):
    data = {
        "name": channel.name,
        "type": channel.type.name,
        "position": channel.position,
        "overwrites": _serialize_overwrites(channel),
    }
    if isinstance(channel, discord.TextChannel):
        data["topic"] = channel.topic
        data["nsfw"] = channel.nsfw
        data["slowmode_delay"] = channel.slowmode_delay
    elif isinstance(channel, discord.VoiceChannel):
        data["bitrate"] = channel.bitrate
        data["user_limit"] = channel.user_limit
    return data


def _serialize_roles(guild):
    return [
        {
            "name": role.name,
            "color": role.color.value,
            "hoist": role.hoist,
            "mentionable": role.mentionable,
            "permissions": role.permissions.value,
            "position": role.position,
        }
        for role in guild.roles
        if not role.is_default()
    ]


def build_scan(guild: discord.Guild) -> dict:
    categories = []
    for category in guild.categories:
        categories.append(
            {
                "name": category.name,
                "position": category.position,
                "overwrites": _serialize_overwrites(category),
                "channels": [_serialize_channel(ch) for ch in category.channels],
            }
        )

    uncategorized = [
        _serialize_channel(ch)
        for ch in guild.channels
        if ch.category is None and not isinstance(ch, discord.CategoryChannel)
    ]

    return {
        "guild_name": guild.name,
        "guild_id": guild.id,
        "created_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "everyone_permissions": guild.default_role.permissions.value,
        "roles": _serialize_roles(guild),
        "categories": categories,
        "uncategorized_channels": uncategorized,
    }


class ConfirmView(discord.ui.View):
    def __init__(self, author_id: int):
        super().__init__(timeout=60)
        self.author_id = author_id
        self.value = None

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.author_id:
            await interaction.response.send_message("Seul l'auteur de la commande peut confirmer.", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="Confirmer le clonage", style=discord.ButtonStyle.danger, emoji="💎")
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.value = True
        self.stop()
        await interaction.response.defer()

    @discord.ui.button(label="Annuler", style=discord.ButtonStyle.secondary)
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.value = False
        self.stop()
        await interaction.response.defer()


class Scan(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    async def scan_autocomplete(self, interaction: discord.Interaction, current: str):
        if not os.path.isdir(SCAN_DIR):
            return []
        files = sorted(os.listdir(SCAN_DIR), reverse=True)
        return [
            app_commands.Choice(name=f, value=f)
            for f in files
            if current.lower() in f.lower()
        ][:25]

    @app_commands.command(name="scan-serveur", description="Scanne intégralement ce serveur (rôles, salons, permissions) et l'enregistre comme base")
    @app_commands.checks.has_permissions(administrator=True)
    async def scan_serveur(self, interaction: discord.Interaction):
        await interaction.response.defer(thinking=True, ephemeral=True)
        guild = interaction.guild
        scan = build_scan(guild)

        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"{_safe_name(guild.name)}_{timestamp}.json"
        save_json(os.path.join(SCAN_DIR, filename), scan)

        channel_count = sum(len(c["channels"]) for c in scan["categories"]) + len(scan["uncategorized_channels"])
        embed = discord.Embed(
            title="💎 Scan terminé",
            description=(
                f"Serveur **{guild.name}** analysé et enregistré comme base.\n\n"
                f"**{len(scan['roles'])}** rôles\n"
                f"**{len(scan['categories'])}** catégories\n"
                f"**{channel_count}** salons"
            ),
            color=discord.Color(COLORS["saphir"]),
        )
        embed.set_footer(text=filename)
        await interaction.followup.send(embed=embed, ephemeral=True)

    @app_commands.command(name="liste-scans", description="Liste les bases de serveur déjà enregistrées par Saphir")
    @app_commands.checks.has_permissions(administrator=True)
    async def liste_scans(self, interaction: discord.Interaction):
        files = sorted(os.listdir(SCAN_DIR), reverse=True) if os.path.isdir(SCAN_DIR) else []
        if not files:
            await interaction.response.send_message("Aucun scan enregistré. Utilise `/scan-serveur` d'abord.", ephemeral=True)
            return
        embed = discord.Embed(
            title="💎 Bases enregistrées",
            description="\n".join(f"`{f}`" for f in files[:25]),
            color=discord.Color(COLORS["saphir"]),
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="cloner-serveur", description="Reconstruit ce serveur à partir d'une base scannée (rôles, catégories, salons, permissions)")
    @app_commands.describe(base="Fichier de base à cloner (voir /liste-scans)")
    @app_commands.autocomplete(base=scan_autocomplete)
    @app_commands.checks.has_permissions(administrator=True)
    async def cloner_serveur(self, interaction: discord.Interaction, base: str):
        guild = interaction.guild
        path = os.path.join(SCAN_DIR, base)
        if not os.path.isfile(path):
            await interaction.response.send_message("Base introuvable. Utilise `/liste-scans`.", ephemeral=True)
            return

        scan = load_json(path, None)
        if scan is None:
            await interaction.response.send_message("Fichier de base illisible.", ephemeral=True)
            return

        view = ConfirmView(interaction.user.id)
        await interaction.response.send_message(
            f"💎 Ceci va **recréer/ajuster** rôles, catégories et salons sur **{guild.name}** "
            f"pour qu'il corresponde à la base de **{scan.get('guild_name', '?')}** (`{base}`).\n"
            "Rien n'est supprimé, mais les permissions des éléments déjà présents du même nom seront écrasées. Continuer ?",
            view=view,
            ephemeral=True,
        )
        await view.wait()
        if not view.value:
            await interaction.edit_original_response(content="Clonage annulé.", view=None)
            return

        await interaction.edit_original_response(content="⏳ Clonage en cours...", view=None)

        report = []

        try:
            await guild.default_role.edit(permissions=discord.Permissions(scan.get("everyone_permissions", 0)))
        except discord.Forbidden:
            report.append("❌ Permissions @everyone non appliquées (permissions insuffisantes)")

        role_map = {}
        for role_data in scan["roles"]:
            role = discord.utils.get(guild.roles, name=role_data["name"])
            color = discord.Color(role_data["color"])
            perms = discord.Permissions(role_data["permissions"])
            try:
                if role is None:
                    role = await guild.create_role(
                        name=role_data["name"],
                        color=color,
                        hoist=role_data["hoist"],
                        mentionable=role_data["mentionable"],
                        permissions=perms,
                        reason="Clonage Saphir",
                    )
                    report.append(f"✅ Rôle créé : {role_data['name']}")
                else:
                    await role.edit(
                        color=color,
                        hoist=role_data["hoist"],
                        mentionable=role_data["mentionable"],
                        permissions=perms,
                        reason="Clonage Saphir",
                    )
                    report.append(f"🔄 Rôle mis à jour : {role_data['name']}")
                role_map[role_data["name"]] = role
            except discord.Forbidden:
                report.append(f"❌ Rôle refusé (permissions) : {role_data['name']}")

        try:
            ordered = sorted(scan["roles"], key=lambda r: r["position"])
            positions = {role_map[r["name"]]: i + 1 for i, r in enumerate(ordered) if r["name"] in role_map}
            if positions:
                await guild.edit_role_positions(positions=positions)
        except (discord.Forbidden, discord.HTTPException):
            report.append("⚠️ Hiérarchie des rôles non réappliquée (rôle du bot probablement trop bas)")

        def resolve_overwrites(entries):
            overwrites = {}
            for entry in entries:
                allow = discord.Permissions(entry["allow"])
                deny = discord.Permissions(entry["deny"])
                ow = discord.PermissionOverwrite.from_pair(allow, deny)
                if entry["kind"] == "role":
                    target = guild.default_role if entry["name"] == "@everyone" else role_map.get(entry["name"])
                else:
                    target = guild.get_member(entry.get("id"))
                if target:
                    overwrites[target] = ow
            return overwrites

        async def clone_channel(category, ch_data):
            overwrites = resolve_overwrites(ch_data["overwrites"])
            pool = category.channels if category else [c for c in guild.channels if c.category is None]
            existing = discord.utils.get(pool, name=ch_data["name"])
            ch_type = ch_data["type"]
            try:
                if ch_type == "voice":
                    if existing is None:
                        await guild.create_voice_channel(
                            ch_data["name"],
                            category=category,
                            overwrites=overwrites,
                            user_limit=ch_data.get("user_limit", 0),
                            reason="Clonage Saphir",
                        )
                        report.append(f"✅ Salon vocal créé : {ch_data['name']}")
                    else:
                        await existing.edit(
                            overwrites=overwrites,
                            user_limit=ch_data.get("user_limit", 0),
                            reason="Clonage Saphir",
                        )
                        report.append(f"🔄 Salon vocal mis à jour : {ch_data['name']}")
                elif ch_type in ("text", "news"):
                    if existing is None:
                        await guild.create_text_channel(
                            ch_data["name"],
                            category=category,
                            overwrites=overwrites,
                            topic=ch_data.get("topic"),
                            nsfw=ch_data.get("nsfw", False),
                            slowmode_delay=ch_data.get("slowmode_delay", 0),
                            reason="Clonage Saphir",
                        )
                        report.append(f"✅ Salon texte créé : {ch_data['name']}")
                    else:
                        await existing.edit(
                            overwrites=overwrites,
                            topic=ch_data.get("topic"),
                            nsfw=ch_data.get("nsfw", False),
                            slowmode_delay=ch_data.get("slowmode_delay", 0),
                            reason="Clonage Saphir",
                        )
                        report.append(f"🔄 Salon texte mis à jour : {ch_data['name']}")
                else:
                    report.append(f"⚠️ Type non pris en charge ({ch_type}) : {ch_data['name']}")
            except discord.Forbidden:
                report.append(f"❌ Salon refusé (permissions) : {ch_data['name']}")

        for cat_data in scan["categories"]:
            category = discord.utils.get(guild.categories, name=cat_data["name"])
            overwrites = resolve_overwrites(cat_data["overwrites"])
            try:
                if category is None:
                    category = await guild.create_category(cat_data["name"], overwrites=overwrites, reason="Clonage Saphir")
                    report.append(f"✅ Catégorie créée : {cat_data['name']}")
                else:
                    await category.edit(overwrites=overwrites, reason="Clonage Saphir")
                    report.append(f"🔄 Catégorie mise à jour : {cat_data['name']}")
            except discord.Forbidden:
                report.append(f"❌ Catégorie refusée (permissions) : {cat_data['name']}")
                continue

            for ch_data in cat_data["channels"]:
                await clone_channel(category, ch_data)

        for ch_data in scan.get("uncategorized_channels", []):
            await clone_channel(None, ch_data)

        text = "\n".join(report) if report else "Rien à faire."
        chunks = [text[i : i + 3900] for i in range(0, len(text), 3900)] or ["Rien à faire."]
        for i, chunk in enumerate(chunks):
            embed = discord.Embed(
                title="💎 Clonage terminé" if i == 0 else "💎 (suite)",
                description=chunk,
                color=discord.Color(COLORS["saphir"]),
            )
            await interaction.followup.send(embed=embed, ephemeral=True)

    @scan_serveur.error
    @liste_scans.error
    @cloner_serveur.error
    async def scan_error(self, interaction: discord.Interaction, error: app_commands.AppCommandError):
        if isinstance(error, app_commands.MissingPermissions):
            await interaction.response.send_message("Seul un administrateur peut utiliser cette commande.", ephemeral=True)


async def setup(bot):
    await bot.add_cog(Scan(bot))
