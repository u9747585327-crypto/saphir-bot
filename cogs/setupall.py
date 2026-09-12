import discord
from discord import app_commands
from discord.ext import commands

from cogs import community, honeypot, logs, stats, voicehub
from cogs._shared import handle_app_error
from config import COLORS


async def _cog_setup(bot, cog_name: str, guild, method: str = "run_setup"):
    """Appelle la méthode de setup d'un cog (les cogs qui ont besoin de leur instance,
    contrairement à ceux dont le run_setup est une simple fonction de module)."""
    cog = bot.get_cog(cog_name)
    if cog is None:
        return [f"⏭️ Cog `{cog_name}` non chargé"]
    return await getattr(cog, method)(guild)


# Ordre imposé par les dépendances réelles entre features :
#  - /setup-administration a besoin des rôles créés par /setup-roles
#  - l'étape « accès staff » de /setup-roles ne fait rien tant que les catégories
#    Alcatraz et Logs n'existent pas → d'où le second passage de setup-roles à la fin
# Le chat IA n'apparaît pas ici : il n'a plus de salon dédié (il répond au ping partout).
STEPS = [
    # 1. créer/réutiliser les rôles OWNER/ADMIN/MODERATOR/MEMBER. Ne supprime JAMAIS un rôle
    #    existant : il est retrouvé par son nom et réutilisé, seuls les manquants sont créés.
    #    La migration/suppression des anciens rôles n'est PAS automatique — elle reste dans la
    #    commande manuelle /nettoyage-roles, à lancer volontairement si un jour tu le veux.
    ("setup-roles", lambda bot, g: _cog_setup(bot, "Hierarchy", g)),
    # 2. les salons, catégorie par catégorie (INFOS d'abord : le honeypot s'y range)
    ("setup-infos", lambda bot, g: community.run_setup(bot, g)),
    ("setup-logs", lambda bot, g: logs.run_setup(bot, g)),
    ("setup-prison", lambda bot, g: _cog_setup(bot, "Prison", g)),
    ("setup-niveaux", lambda bot, g: _cog_setup(bot, "Leveling", g)),
    ("setup-vocal", lambda bot, g: voicehub.run_setup(bot, g)),
    ("setup-honeypot", lambda bot, g: honeypot.run_setup(bot, g)),
    ("setup-stats", lambda bot, g: stats.run_setup(bot, g)),
    ("setup-administration", lambda bot, g: _cog_setup(bot, "Hierarchy", g, "run_setup_administration")),
    # 4. 2e passage : applique l'accès staff aux catégories qui viennent d'être créées
    ("setup-roles (2e passage)", lambda bot, g: _cog_setup(bot, "Hierarchy", g)),
]


async def _execute_steps(bot, guild) -> list:
    """Exécute toutes les étapes de configuration et renvoie le résumé (une ligne / étape)."""
    summary = []
    for label, step in STEPS:
        try:
            report = await step(bot, guild)
            failures = sum(1 for line in report if line.startswith("❌") or line.startswith("⚠️"))
            summary.append(f"⚠️ `/{label}` — {failures} problème(s)" if failures else f"✅ `/{label}`")
        except Exception as e:
            print(f"⚠️ configuration : échec à l'étape {label} : {type(e).__name__}: {e}")
            summary.append(f"❌ `/{label}` — {e}")
    return summary


async def _purge_all(guild: discord.Guild) -> dict:
    """Efface TOUT pour repartir de zéro : tous les salons, toutes les catégories, et tous
    les rôles supprimables. À lancer AVANT la reconstruction. Protège absolument (non
    supprimables de toute façon) : @everyone, les rôles gérés par une intégration (bots,
    boost), et tout rôle au-dessus du bot. Chaque suppression est isolée pour ne pas
    s'arrêter sur un salon système (règles/annonces d'un serveur communautaire)."""
    stats = {"salons": 0, "categories": 0, "roles": 0}

    for channel in list(guild.channels):
        if isinstance(channel, discord.CategoryChannel):
            continue
        try:
            await channel.delete(reason="Reset serveur — repart de zéro (Saphir)")
            stats["salons"] += 1
        except discord.HTTPException:
            pass

    for category in list(guild.categories):
        try:
            await category.delete(reason="Reset serveur — repart de zéro (Saphir)")
            stats["categories"] += 1
        except discord.HTTPException:
            pass

    me_top = guild.me.top_role
    for role in list(guild.roles):
        if role.is_default() or role.managed or role.position >= me_top.position:
            continue
        try:
            await role.delete(reason="Reset serveur — repart de zéro (Saphir)")
            stats["roles"] += 1
        except discord.HTTPException:
            pass

    return stats


class ConfirmResetServer(discord.ui.View):
    def __init__(self, author_id: int):
        super().__init__(timeout=30)
        self.author_id = author_id
        self.value = False

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.author_id:
            await interaction.response.send_message("Ce n'est pas ta confirmation.", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="Oui, tout nettoyer", style=discord.ButtonStyle.danger, emoji="🗑️")
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.value = True
        self.stop()
        await interaction.response.defer()

    @discord.ui.button(label="Annuler", style=discord.ButtonStyle.secondary)
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.value = False
        self.stop()
        await interaction.response.defer()


class SetupAll(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(
        name="setup-tout",
        description="Lance toute la configuration du serveur, dans l'ordre imposé par les dépendances",
    )
    @app_commands.checks.has_permissions(administrator=True)
    async def setup_tout(self, interaction: discord.Interaction):
        await interaction.response.defer(thinking=True, ephemeral=True)
        summary = await _execute_steps(self.bot, interaction.guild)
        embed = discord.Embed(
            title="🧰 Configuration complète",
            description="\n".join(summary),
            color=discord.Color(COLORS["saphir"]),
        )
        embed.set_footer(text="Relance une commande précise pour voir son rapport détaillé")
        await interaction.followup.send(embed=embed, ephemeral=True)

    @app_commands.command(
        name="reset-serveur",
        description="⚠️ Config propre PUIS suppression de TOUS les autres salons/rôles (irréversible)",
    )
    @app_commands.checks.has_permissions(administrator=True)
    async def reset_serveur(self, interaction: discord.Interaction):
        guild = interaction.guild
        view = ConfirmResetServer(interaction.user.id)
        await interaction.response.send_message(
            "⚠️ **Attention — action irréversible : repart de ZÉRO.**\n"
            "Je vais **supprimer TOUS les salons** (tout l'historique de messages sera perdu) "
            "**et TOUS les rôles** (les membres perdront tous leurs rôles), puis reconstruire la "
            "structure Saphir propre (rôles + salons au thème).\n\n"
            "Sont **protégés** (non supprimables) : les bots et leurs rôles, le boost, @everyone, "
            "le rôle de Saphir et les rôles au-dessus de lui.\n\n"
            "Continuer ?",
            view=view, ephemeral=True,
        )
        await view.wait()
        if not view.value:
            await interaction.edit_original_response(content="Reset annulé — rien n'a été touché.", view=None)
            return

        await interaction.edit_original_response(content="⏳ Suppression totale puis reconstruction en cours...", view=None)
        purged = await _purge_all(guild)          # 1. on efface tout
        summary = await _execute_steps(self.bot, guild)  # 2. on reconstruit de zéro

        embed = discord.Embed(
            title="🧹 Serveur reconstruit de zéro",
            description=(
                f"**Nettoyage :** 🗑️ {purged['salons']} salon(s), "
                f"{purged['categories']} catégorie(s), {purged['roles']} rôle(s) supprimé(s).\n\n"
                "**Structure Saphir recréée :**\n" + "\n".join(summary)
            ),
            color=discord.Color(COLORS["saphir"]),
        )
        await interaction.followup.send(embed=embed, ephemeral=True)

    @setup_tout.error
    @reset_serveur.error
    async def setup_tout_error(self, interaction: discord.Interaction, error: app_commands.AppCommandError):
        await handle_app_error(
            interaction, error,
            perm_message="Seul un administrateur peut utiliser cette commande.",
            command_label="setup-tout",
        )


async def setup(bot):
    await bot.add_cog(SetupAll(bot))
