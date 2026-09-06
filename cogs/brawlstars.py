import os

import aiohttp
import discord
from discord import app_commands
from discord.ext import commands

from cogs._shared import SaphirModal, handle_app_error
from config import (
    BRAWLSTARS_API_BASE,
    BRAWLSTARS_CATEGORY_NAME,
    BRAWLSTARS_INFO_CHANNEL_NAME,
    BRAWLSTARS_LINKS_FILE,
    COLORS,
)
from storage import aload_json, asave_json

INFO_TEXT = (
    "🎮 **Commandes Brawl Stars**\n\n"
    "- `/lier-brawlstars` — relie ton compte Discord à ton tag de joueur.\n"
    "- `/brawlstats [membre]` — affiche les stats du compte relié (toi par défaut).\n"
    "- `/brawlclub` — affiche les infos d'un club via son tag.\n\n"
    "Ces commandes fonctionnent dans n'importe quel salon du serveur."
)

# clé générée sur developer.brawlstars.com — IMPORTANT : elle doit être verrouillée sur l'IP
# du proxy RoyaleAPI (45.79.218.79 au moment de l'écriture, voir docs.royaleapi.com/proxy.html),
# pas sur l'IP de Render qui change à chaque redéploiement.
_API_KEY = os.environ.get("BRAWLSTARS_API_KEY")
_API_BASE = os.environ.get("BRAWLSTARS_API_BASE", BRAWLSTARS_API_BASE)

VALID_TAG_CHARS = set("0289PYLQGRJCUV")


def is_configured() -> bool:
    return bool(_API_KEY)


def _normalize_tag(raw: str) -> str:
    """Nettoie un tag saisi par un humain (espaces, minuscules, # optionnel) et l'encode
    pour l'URL (l'API attend %23 à la place du #, sinon aiohttp lirait # comme un fragment)."""
    tag = raw.strip().upper().lstrip("#").replace(" ", "")
    return "%23" + tag


def _tag_is_plausible(raw: str) -> bool:
    tag = raw.strip().upper().lstrip("#").replace(" ", "")
    return 3 <= len(tag) <= 14 and all(c in VALID_TAG_CHARS for c in tag)


async def _bs_get(path: str):
    """Retourne (data, erreur). `erreur` est None en cas de succès, sinon un code parmi :
    "not_configured", "not_found", "forbidden", "rate_limited", "http_<code>", "network"."""
    if not _API_KEY:
        return None, "not_configured"
    headers = {"Authorization": f"Bearer {_API_KEY}"}
    url = f"{_API_BASE}/{path}"
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, headers=headers, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                if resp.status == 200:
                    return await resp.json(), None
                if resp.status == 404:
                    return None, "not_found"
                if resp.status == 403:
                    return None, "forbidden"
                if resp.status == 429:
                    return None, "rate_limited"
                return None, f"http_{resp.status}"
    except (aiohttp.ClientError, TimeoutError):
        return None, "network"


def _error_message(error: str) -> str:
    return {
        "not_configured": "🔌 La clé API Brawl Stars n'est pas configurée sur le bot.",
        "not_found": "❌ Tag introuvable — vérifie l'orthographe (visible dans le jeu, sous ton pseudo).",
        "forbidden": (
            "❌ Clé API refusée par Supercell. Vérifie qu'elle est bien verrouillée sur l'IP du "
            "proxy RoyaleAPI (45.79.218.79), pas sur l'IP du serveur."
        ),
        "rate_limited": "⏳ Trop de requêtes vers l'API Brawl Stars, réessaie dans une minute.",
        "network": "❌ Impossible de joindre l'API Brawl Stars (réseau).",
    }.get(error, f"❌ Erreur API Brawl Stars ({error}).")


async def _get_link(guild_id: int, user_id: int) -> str | None:
    data = await aload_json(BRAWLSTARS_LINKS_FILE, {})
    return data.get(str(guild_id), {}).get(str(user_id))


async def _set_link(guild_id: int, user_id: int, tag: str):
    data = await aload_json(BRAWLSTARS_LINKS_FILE, {})
    data.setdefault(str(guild_id), {})[str(user_id)] = tag
    await asave_json(BRAWLSTARS_LINKS_FILE, data)


class ConfirmLinkView(discord.ui.View):
    """Affiche le profil trouvé et n'enregistre le lien que si l'auteur confirme —
    évite de lier le mauvais tag suite à une faute de frappe."""

    def __init__(self, author_id: int, guild_id: int, tag: str):
        super().__init__(timeout=60)
        self.author_id = author_id
        self.guild_id = guild_id
        self.tag = tag

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.author_id:
            await interaction.response.send_message("Seul l'auteur de la commande peut confirmer.", ephemeral=True)
            return False
        return True

    async def _disable_and_edit(self, interaction: discord.Interaction, content: str):
        for child in self.children:
            child.disabled = True
        self.stop()
        await interaction.response.edit_message(content=content, embed=None, view=self)

    @discord.ui.button(label="Confirmer", style=discord.ButtonStyle.success, emoji="✅")
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button):
        await _set_link(self.guild_id, self.author_id, self.tag)
        await self._disable_and_edit(interaction, f"✅ Compte relié : {self.tag}.")

    @discord.ui.button(label="Annuler", style=discord.ButtonStyle.secondary)
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._disable_and_edit(interaction, "Annulé — aucun compte relié.")


class LinkTagModal(SaphirModal, title="🔗 Lier un compte Brawl Stars"):
    error_label = "lier-brawlstars"
    tag = discord.ui.TextInput(label="Tag Brawl Stars", placeholder="ABC123 (le # est facultatif)", min_length=3, max_length=14)

    async def on_submit(self, interaction: discord.Interaction):
        raw = str(self.tag.value)
        if not _tag_is_plausible(raw):
            await interaction.response.send_message(
                "❌ Ce tag ne ressemble pas à un tag Brawl Stars valide (ex : ABC123).", ephemeral=True
            )
            return

        await interaction.response.defer(thinking=True, ephemeral=True)
        normalized = _normalize_tag(raw)
        data, error = await _bs_get(f"players/{normalized}")
        if error:
            await interaction.followup.send(_error_message(error), ephemeral=True)
            return

        display_tag = normalized.replace("%23", "#")
        club = data.get("club")
        embed = discord.Embed(title=f"🎮 {data['name']}", description=display_tag, color=discord.Color(COLORS["gold"]))
        embed.add_field(name="🏆 Trophées", value=str(data["trophies"]))
        embed.add_field(name="🏟️ Club", value=club["name"] if club else "Aucun")

        view = ConfirmLinkView(interaction.user.id, interaction.guild.id, display_tag)
        await interaction.followup.send(
            content="Voici le profil trouvé — c'est bien toi ?", embed=embed, view=view, ephemeral=True
        )


class ClubTagModal(SaphirModal, title="🏟️ Rechercher un club Brawl Stars"):
    error_label = "brawlclub"
    tag = discord.ui.TextInput(label="Tag du club", placeholder="ABC123 (le # est facultatif)", min_length=3, max_length=14)

    async def on_submit(self, interaction: discord.Interaction):
        raw = str(self.tag.value)
        if not _tag_is_plausible(raw):
            await interaction.response.send_message(
                "❌ Ce tag ne ressemble pas à un tag Brawl Stars valide (ex : ABC123).", ephemeral=True
            )
            return

        await interaction.response.defer(thinking=True)
        data, error = await _bs_get(f"clubs/{_normalize_tag(raw)}")
        if error:
            await interaction.followup.send(_error_message(error))
            return

        members = data.get("members", [])
        top_members = "\n".join(f"🏆 {m['trophies']} — {m['name']} ({m['role'].capitalize()})" for m in members[:5])

        embed = discord.Embed(
            title=f"🏟️ {data['name']}",
            description=data.get("description") or "*(pas de description)*",
            color=discord.Color(COLORS["gold"]),
        )
        embed.add_field(name="🏆 Trophées du club", value=str(data["trophies"]))
        embed.add_field(name="👥 Membres", value=f"{len(members)}/30")
        embed.add_field(name="🔓 Type", value=data["type"].capitalize())
        if top_members:
            embed.add_field(name="Top membres", value=top_members, inline=False)
        await interaction.followup.send(embed=embed)


class BrawlStars(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="setup-brawlstars", description="Crée le salon d'information Brawl Stars")
    @app_commands.checks.has_permissions(administrator=True)
    async def setup_brawlstars(self, interaction: discord.Interaction):
        await interaction.response.defer(thinking=True, ephemeral=True)
        guild = interaction.guild
        report = []

        category = discord.utils.get(guild.categories, name=BRAWLSTARS_CATEGORY_NAME)
        try:
            if category is None:
                category = await guild.create_category(BRAWLSTARS_CATEGORY_NAME, reason="Configuration Brawl Stars (Saphir)")
                report.append(f"✅ Catégorie créée : {BRAWLSTARS_CATEGORY_NAME}")
            else:
                report.append(f"= Catégorie déjà présente : {BRAWLSTARS_CATEGORY_NAME}")
        except discord.Forbidden:
            await interaction.followup.send("❌ Permissions insuffisantes pour créer la catégorie.", ephemeral=True)
            return

        readonly_overwrites = {guild.default_role: discord.PermissionOverwrite(send_messages=False)}
        info_channel = discord.utils.get(category.channels, name=BRAWLSTARS_INFO_CHANNEL_NAME)
        try:
            if info_channel is None:
                info_channel = await guild.create_text_channel(
                    BRAWLSTARS_INFO_CHANNEL_NAME, category=category, overwrites=readonly_overwrites,
                    reason="Configuration Brawl Stars (Saphir)",
                )
                report.append(f"✅ Salon créé : {info_channel.mention}")
            else:
                await info_channel.edit(overwrites=readonly_overwrites, reason="Configuration Brawl Stars (Saphir)")
                report.append(f"= Salon déjà présent : {info_channel.mention}")

            already_posted = False
            async for msg in info_channel.history(limit=10):
                if msg.author.id == self.bot.user.id and msg.embeds and msg.embeds[0].footer.text == "Saphir · Brawl Stars info":
                    already_posted = True
                    break
            if not already_posted:
                info_embed = discord.Embed(description=INFO_TEXT, color=discord.Color(COLORS["gold"]))
                info_embed.set_footer(text="Saphir · Brawl Stars info")
                await info_channel.send(embed=info_embed)
        except discord.Forbidden:
            report.append(f"❌ Salon refusé (permissions) : {BRAWLSTARS_INFO_CHANNEL_NAME}")

        embed = discord.Embed(
            title="🎮 Configuration Brawl Stars", description="\n".join(report), color=discord.Color(COLORS["saphir"])
        )
        await interaction.followup.send(embed=embed, ephemeral=True)

    @app_commands.command(name="lier-brawlstars", description="Relie ton compte Discord à ton tag de joueur Brawl Stars")
    async def lier_brawlstars(self, interaction: discord.Interaction):
        await interaction.response.send_modal(LinkTagModal())

    @app_commands.command(name="brawlstats", description="Affiche les stats Brawl Stars d'un membre (ou toi par défaut)")
    @app_commands.describe(membre="Membre dont voir les stats (toi par défaut si son compte est relié)")
    async def brawlstats(self, interaction: discord.Interaction, membre: discord.Member = None):
        target = membre or interaction.user
        tag = await _get_link(interaction.guild.id, target.id)
        if tag is None:
            who = "Tu n'as" if target == interaction.user else f"{target.mention} n'a"
            await interaction.response.send_message(
                f"{who} pas encore relié de compte Brawl Stars. Utilise `/lier-brawlstars`.", ephemeral=True
            )
            return

        await interaction.response.defer(thinking=True)
        data, error = await _bs_get(f"players/{_normalize_tag(tag)}")
        if error:
            await interaction.followup.send(_error_message(error))
            return

        club = data.get("club")
        embed = discord.Embed(title=f"🎮 {data['name']}", description=tag, color=discord.Color(COLORS["gold"]))
        embed.add_field(name="🏆 Trophées", value=f"{data['trophies']} (record : {data['highestTrophies']})")
        embed.add_field(name="⭐ Niveau d'XP", value=str(data["expLevel"]))
        embed.add_field(name="🎯 Brawlers débloqués", value=str(len(data.get("brawlers", []))))
        embed.add_field(name="🏅 Victoires 3c3", value=str(data.get("3vs3Victories", 0)))
        embed.add_field(name="🥊 Victoires Duo", value=str(data.get("duoVictories", 0)))
        embed.add_field(name="👤 Victoires Solo", value=str(data.get("soloVictories", 0)))
        embed.add_field(name="🏟️ Club", value=club["name"] if club else "Aucun", inline=False)
        embed.set_image(url=target.display_avatar.with_size(512).url)
        await interaction.followup.send(embed=embed)

    @app_commands.command(name="brawlclub", description="Affiche les infos d'un club Brawl Stars via son tag")
    async def brawlclub(self, interaction: discord.Interaction):
        await interaction.response.send_modal(ClubTagModal())

    @setup_brawlstars.error
    @lier_brawlstars.error
    @brawlstats.error
    @brawlclub.error
    async def brawlstars_error(self, interaction: discord.Interaction, error: app_commands.AppCommandError):
        await handle_app_error(interaction, error, command_label="Brawl Stars")


async def setup(bot):
    await bot.add_cog(BrawlStars(bot))
