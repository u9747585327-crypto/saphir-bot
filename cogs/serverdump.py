import io
import json

import discord
from discord import app_commands
from discord.ext import commands

from cogs._shared import handle_app_error
from config import GUILD_SETTINGS_FILE
from storage import aload_json

# permissions qu'on liste explicitement pour chaque rôle (les seules qui comptent pour
# comprendre qui peut quoi) — évite de vider les ~50 permissions Discord dans l'export
KEY_PERMS = [
    "administrator", "manage_guild", "manage_roles", "manage_channels",
    "ban_members", "kick_members", "moderate_members", "manage_messages",
    "mute_members", "deafen_members", "move_members",
    "view_channel", "connect", "speak", "send_messages", "manage_webhooks",
]

# permissions résumées par salon dans les surcharges (overwrites)
OVERWRITE_PERMS = ["view_channel", "connect", "speak", "send_messages", "manage_channels"]

CHANNEL_TYPES = {
    discord.ChannelType.text: "texte",
    discord.ChannelType.voice: "vocal",
    discord.ChannelType.category: "catégorie",
    discord.ChannelType.news: "annonces",
    discord.ChannelType.stage_voice: "conférence",
    discord.ChannelType.forum: "forum",
}


def _perms_list(permissions: discord.Permissions) -> list:
    return [name for name in KEY_PERMS if getattr(permissions, name, False)]


def _overwrites_summary(channel: discord.abc.GuildChannel) -> list:
    """Résumé compact des surcharges : pour chaque rôle/membre visé, les permissions
    de OVERWRITE_PERMS explicitement autorisées (+) ou refusées (-)."""
    summary = []
    for target, overwrite in channel.overwrites.items():
        allow, deny = overwrite.pair()
        plus = [p for p in OVERWRITE_PERMS if getattr(allow, p, False)]
        minus = [p for p in OVERWRITE_PERMS if getattr(deny, p, False)]
        if not plus and not minus:
            continue
        kind = "role" if isinstance(target, discord.Role) else "membre"
        summary.append({
            "cible": f"{target.name} ({kind})",
            "id": target.id,
            "autorise": plus,
            "refuse": minus,
        })
    return summary


def _channel_dict(channel: discord.abc.GuildChannel) -> dict:
    d = {
        "nom": channel.name,
        "id": channel.id,
        "type": CHANNEL_TYPES.get(channel.type, str(channel.type)),
        "position": channel.position,
    }
    if isinstance(channel, discord.VoiceChannel):
        d["limite_places"] = channel.user_limit
        d["bitrate"] = channel.bitrate
    overwrites = _overwrites_summary(channel)
    if overwrites:
        d["surcharges"] = overwrites
    return d


def build_snapshot(guild: discord.Guild, settings: dict) -> dict:
    afk = guild.afk_channel
    snapshot = {
        "serveur": {
            "nom": guild.name,
            "id": guild.id,
            "membres": guild.member_count,
            "salon_afk": afk.name if afk else None,
            "proprietaire_id": guild.owner_id,
        },
        "roles": [],
        "categories": [],
        "salons_hors_categorie": [],
        "reglages_bot": settings.get(str(guild.id), {}),
    }

    # rôles, du plus haut au plus bas
    for role in sorted(guild.roles, key=lambda r: r.position, reverse=True):
        snapshot["roles"].append({
            "nom": role.name,
            "id": role.id,
            "position": role.position,
            "couleur": f"#{role.color.value:06X}" if role.color.value else None,
            "affiche_separement": role.hoist,
            "gere_par_integration": role.managed,
            "membres": len(role.members),
            "permissions_cles": _perms_list(role.permissions),
        })

    # salons regroupés par catégorie, dans l'ordre affiché
    for category, channels in guild.by_category():
        entry = {
            "nom": category.name if category else None,
            "id": category.id if category else None,
            "salons": [_channel_dict(c) for c in channels],
        }
        if category is None:
            snapshot["salons_hors_categorie"] = entry["salons"]
        else:
            snapshot["categories"].append(entry)

    return snapshot


class ServerDump(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(
        name="export-serveur",
        description="Génère un fichier avec tous les salons, rôles et réglages (à envoyer pour analyse)",
    )
    @app_commands.checks.has_permissions(administrator=True)
    async def export_serveur(self, interaction: discord.Interaction):
        await interaction.response.defer(thinking=True, ephemeral=True)
        settings = await aload_json(GUILD_SETTINGS_FILE, {})
        snapshot = build_snapshot(interaction.guild, settings)

        payload = json.dumps(snapshot, ensure_ascii=False, indent=2)
        file = discord.File(
            io.BytesIO(payload.encode("utf-8")),
            filename=f"serveur-{interaction.guild.id}.json",
        )
        nb_salons = sum(len(c["salons"]) for c in snapshot["categories"]) + len(snapshot["salons_hors_categorie"])
        await interaction.followup.send(
            content=(
                f"📦 Export de **{interaction.guild.name}** : "
                f"{len(snapshot['roles'])} rôle(s), {len(snapshot['categories'])} catégorie(s), "
                f"{nb_salons} salon(s).\n"
                "Télécharge ce fichier et envoie-le dans la conversation pour analyse."
            ),
            file=file,
            ephemeral=True,
        )

    @export_serveur.error
    async def export_serveur_error(self, interaction: discord.Interaction, error: app_commands.AppCommandError):
        await handle_app_error(
            interaction, error,
            perm_message="Seul un administrateur peut exporter le serveur.",
            command_label="export-serveur",
        )


async def setup(bot):
    await bot.add_cog(ServerDump(bot))
