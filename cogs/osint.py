import datetime

import discord
from discord import app_commands
from discord.ext import commands

from config import (
    COLORS,
    OSINT_CATEGORY_NAME,
    OSINT_COMMAND_CHANNEL_NAME,
    OSINT_DAILY_LIMIT,
    OSINT_INFO_CHANNEL_NAME,
    OSINT_ROLE_NAME,
    OSINT_USAGE_FILE,
)
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

    @app_commands.command(
        name="setup-osint",
        description="Crée la catégorie de recherche de profil Discord (salon explicatif + salon de commande)",
    )
    @app_commands.checks.has_permissions(administrator=True)
    async def setup_osint(self, interaction: discord.Interaction):
        await interaction.response.defer(thinking=True, ephemeral=True)
        guild = interaction.guild
        report = []

        role = discord.utils.get(guild.roles, name=OSINT_ROLE_NAME)
        if role is None:
            report.append(f"⚠️ Le rôle `{OSINT_ROLE_NAME}` n'existe pas encore — lance `/setup-niveaux` d'abord.")

        category = discord.utils.get(guild.categories, name=OSINT_CATEGORY_NAME)
        try:
            if category is None:
                category = await guild.create_category(OSINT_CATEGORY_NAME, reason="Configuration OSINT (Saphir)")
                report.append(f"✅ Catégorie créée : {OSINT_CATEGORY_NAME}")
            else:
                report.append(f"= Catégorie déjà présente : {OSINT_CATEGORY_NAME}")
        except discord.Forbidden:
            await interaction.followup.send("❌ Permissions insuffisantes pour créer la catégorie.", ephemeral=True)
            return

        readonly_overwrites = {guild.default_role: discord.PermissionOverwrite(send_messages=False)}
        info_channel = discord.utils.get(category.channels, name=OSINT_INFO_CHANNEL_NAME)
        try:
            if info_channel is None:
                info_channel = await guild.create_text_channel(
                    OSINT_INFO_CHANNEL_NAME, category=category, overwrites=readonly_overwrites, reason="Configuration OSINT (Saphir)"
                )
                report.append(f"✅ Salon créé : {OSINT_INFO_CHANNEL_NAME}")
            else:
                await info_channel.edit(overwrites=readonly_overwrites, reason="Configuration OSINT (Saphir)")
                report.append(f"= Salon déjà présent : {OSINT_INFO_CHANNEL_NAME}")

            already_posted = False
            async for msg in info_channel.history(limit=10):
                if msg.author.id == self.bot.user.id and msg.embeds and msg.embeds[0].footer.text == "Saphir · OSINT info":
                    already_posted = True
                    break
            if not already_posted:
                info_embed = discord.Embed(description=INFO_TEXT, color=discord.Color(COLORS["saphir"]))
                info_embed.set_footer(text="Saphir · OSINT info")
                await info_channel.send(embed=info_embed)
        except discord.Forbidden:
            report.append(f"❌ Salon refusé (permissions) : {OSINT_INFO_CHANNEL_NAME}")

        command_overwrites = {guild.default_role: discord.PermissionOverwrite(view_channel=False)}
        if role:
            command_overwrites[role] = discord.PermissionOverwrite(view_channel=True, send_messages=True)

        command_channel = discord.utils.get(category.channels, name=OSINT_COMMAND_CHANNEL_NAME)
        try:
            if command_channel is None:
                command_channel = await guild.create_text_channel(
                    OSINT_COMMAND_CHANNEL_NAME, category=category, overwrites=command_overwrites, reason="Configuration OSINT (Saphir)"
                )
                report.append(f"✅ Salon créé : {OSINT_COMMAND_CHANNEL_NAME} (réservé au rôle {OSINT_ROLE_NAME})")
            else:
                await command_channel.edit(overwrites=command_overwrites, reason="Configuration OSINT (Saphir)")
                report.append(f"= Salon déjà présent : {OSINT_COMMAND_CHANNEL_NAME}")
        except discord.Forbidden:
            report.append(f"❌ Salon refusé (permissions) : {OSINT_COMMAND_CHANNEL_NAME}")

        embed = discord.Embed(title="🔍 Configuration OSINT", description="\n".join(report), color=discord.Color(COLORS["saphir"]))
        await interaction.followup.send(embed=embed, ephemeral=True)

    @setup_osint.error
    async def setup_osint_error(self, interaction: discord.Interaction, error: app_commands.AppCommandError):
        if isinstance(error, app_commands.MissingPermissions):
            await interaction.response.send_message("Seul un administrateur peut utiliser cette commande.", ephemeral=True)

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
        await interaction.response.send_message(f"Une erreur est survenue : {error}", ephemeral=True)


async def setup(bot):
    await bot.add_cog(Osint(bot))
