import datetime

import discord
from discord import app_commands
from discord.ext import commands

from cogs._shared import handle_app_error
from config import (
    COLORS,
    OSINT_CATEGORY_NAME,
    OSINT_COMMAND_CHANNEL_NAME,
    OSINT_DAILY_LIMIT,
    OSINT_INFO_CHANNEL_NAME,
    OSINT_ROLE_NAME,
    OSINT_USAGE_FILE,
)
from services.setup_kit import ensure_category, ensure_text_channel, hidden_overwrites, post_once, readonly_overwrites
from storage import load_json, save_json

PUBLIC_FLAG_LABELS = {
    "staff": "Staff Discord",
    "partner": "Partenaire Discord",
    "hypesquad": "HypeSquad",
    "bug_hunter": "Bug Hunter",
    "bug_hunter_level_2": "Bug Hunter Niveau 2",
    "hypesquad_bravery": "HypeSquad Bravery",
    "hypesquad_brilliance": "HypeSquad Brilliance",
    "hypesquad_balance": "HypeSquad Balance",
    "early_supporter": "Early Supporter",
    "verified_bot_developer": "Développeur de bot vérifié",
    "active_developer": "Développeur actif",
    "verified_bot": "Bot vérifié",
    "discord_certified_moderator": "Modérateur certifié Discord",
}


def _today() -> str:
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d")


INFO_TEXT = (
    "🔍 **Recherche de profil Discord**\n\n"
    "Cette commande n'affiche **que des informations publiques Discord** : avatar, "
    "date de création du compte, badges publics, et — si la personne est sur ce serveur — "
    "sa date d'arrivée et ses rôles.\n\n"
    "**Aucune donnée personnelle, aucune fuite, aucune base tierce.** Tout provient "
    "directement de l'API officielle Discord, la même chose que tu verrais en cliquant "
    "sur le profil de quelqu'un.\n\n"
    f"⚠️ Limite : **{OSINT_DAILY_LIMIT} recherches par jour** par membre."
)


class Osint(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    # ------------------------------------------------------------------ #
    #  Setup
    # ------------------------------------------------------------------ #

    async def run_setup(self, guild: discord.Guild) -> list:
        """Logique de /setup-osint, appelable aussi par /setup-tout."""
        report = []

        role = discord.utils.get(guild.roles, name=OSINT_ROLE_NAME)
        if role is None:
            report.append(f"⚠️ Le rôle `{OSINT_ROLE_NAME}` n'existe pas encore — lance `/setup-niveaux` d'abord.")

        category, line = await ensure_category(guild, OSINT_CATEGORY_NAME)
        report.append(line)
        if category is None:
            return report

        info_channel, line = await ensure_text_channel(
            guild, OSINT_INFO_CHANNEL_NAME, category=category, overwrites=readonly_overwrites(guild)
        )
        report.append(line)

        info_embed = discord.Embed(description=INFO_TEXT, color=discord.Color(COLORS["saphir"]))
        if await post_once(info_channel, self.bot.user.id, info_embed, "Saphir · OSINT info"):
            report.append("📝 Message d'explication posté")

        _command_channel, line = await ensure_text_channel(
            guild, OSINT_COMMAND_CHANNEL_NAME, category=category, overwrites=hidden_overwrites(guild, role)
        )
        report.append(line)
        return report

    @app_commands.command(
        name="setup-osint",
        description="Crée la catégorie de recherche de profil Discord (salon explicatif + salon de commande)",
    )
    @app_commands.checks.has_permissions(administrator=True)
    async def setup_osint(self, interaction: discord.Interaction):
        await interaction.response.defer(thinking=True, ephemeral=True)
        report = await self.run_setup(interaction.guild)
        embed = discord.Embed(title="🔍 Configuration OSINT", description="\n".join(report), color=discord.Color(COLORS["saphir"]))
        await interaction.followup.send(embed=embed, ephemeral=True)

    @setup_osint.error
    async def setup_osint_error(self, interaction: discord.Interaction, error: app_commands.AppCommandError):
        await handle_app_error(
            interaction, error,
            perm_message="Seul un administrateur peut utiliser cette commande.",
            command_label="setup-osint",
        )

    # ------------------------------------------------------------------ #
    #  Recherche
    # ------------------------------------------------------------------ #

    def _check_and_consume_quota(self, guild_id: int, user_id: int) -> int:
        """Retourne le nombre de recherches restantes après consommation (-1 si quota dépassé)."""
        data = load_json(OSINT_USAGE_FILE, {})
        guild_data = data.setdefault(str(guild_id), {})
        entry = guild_data.get(str(user_id))
        today = _today()

        if entry is None or entry.get("date") != today:
            entry = {"date": today, "count": 0}

        if entry["count"] >= OSINT_DAILY_LIMIT:
            guild_data[str(user_id)] = entry
            save_json(OSINT_USAGE_FILE, data)
            return -1

        entry["count"] += 1
        guild_data[str(user_id)] = entry
        save_json(OSINT_USAGE_FILE, data)
        return OSINT_DAILY_LIMIT - entry["count"]

    @app_commands.command(name="recherche-discord", description="Affiche les infos de profil Discord publiques d'un membre")
    @app_commands.describe(
        membre="Membre du serveur à rechercher (si présent ici)",
        user_id="ID Discord à rechercher (si la personne n'est pas sur ce serveur)",
    )
    async def recherche_discord(
        self,
        interaction: discord.Interaction,
        membre: discord.Member = None,
        user_id: str = None,
    ):
        role = discord.utils.get(interaction.guild.roles, name=OSINT_ROLE_NAME)
        member_perms = interaction.user.guild_permissions
        if not member_perms.administrator and (role is None or role not in interaction.user.roles):
            await interaction.response.send_message(
                f"🔒 Il faut le rôle {OSINT_ROLE_NAME} pour utiliser cette commande (monte de niveau pour le débloquer).",
                ephemeral=True,
            )
            return

        if interaction.channel.name != OSINT_COMMAND_CHANNEL_NAME:
            await interaction.response.send_message(
                f"Utilise cette commande dans le salon {OSINT_COMMAND_CHANNEL_NAME}.", ephemeral=True
            )
            return

        if membre is None and not user_id:
            await interaction.response.send_message("Précise un membre ou un ID Discord à rechercher.", ephemeral=True)
            return

        if not member_perms.administrator:
            remaining = self._check_and_consume_quota(interaction.guild.id, interaction.user.id)
            if remaining < 0:
                await interaction.response.send_message(
                    f"⛔ Tu as atteint la limite de {OSINT_DAILY_LIMIT} recherches aujourd'hui. Réessaie demain.",
                    ephemeral=True,
                )
                return

        await interaction.response.defer(thinking=True)

        target = membre
        if target is None:
            try:
                target = await self.bot.fetch_user(int(user_id))
            except (ValueError, discord.NotFound):
                await interaction.followup.send("❌ ID Discord introuvable.", ephemeral=True)
                return

        age = discord.utils.utcnow() - target.created_at
        badges = [PUBLIC_FLAG_LABELS[f.name] for f in target.public_flags.all() if f.name in PUBLIC_FLAG_LABELS] if hasattr(target, "public_flags") else []

        embed = discord.Embed(title=f"🔍 {target}", color=discord.Color(COLORS["saphir"]))
        embed.set_thumbnail(url=target.display_avatar.url)
        embed.add_field(name="ID", value=str(target.id), inline=False)
        embed.add_field(name="Compte créé", value=f"{discord.utils.format_dt(target.created_at, style='F')} ({age.days} jours)", inline=False)
        embed.add_field(name="Badges publics", value=", ".join(badges) if badges else "Aucun", inline=False)

        member_here = interaction.guild.get_member(target.id)
        if member_here:
            embed.add_field(
                name="Sur ce serveur depuis",
                value=discord.utils.format_dt(member_here.joined_at, style="R") if member_here.joined_at else "Inconnu",
                inline=False,
            )
            roles = [r.mention for r in member_here.roles if not r.is_default()]
            embed.add_field(name="Rôles", value=", ".join(roles) if roles else "Aucun", inline=False)
        else:
            embed.add_field(name="Sur ce serveur", value="Non", inline=False)

        embed.set_footer(text="Données publiques Discord uniquement")
        await interaction.followup.send(embed=embed)

    @recherche_discord.error
    async def recherche_discord_error(self, interaction: discord.Interaction, error: app_commands.AppCommandError):
        await handle_app_error(interaction, error, command_label="recherche-discord")


async def setup(bot):
    await bot.add_cog(Osint(bot))
