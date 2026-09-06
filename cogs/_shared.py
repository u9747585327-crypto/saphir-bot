"""Utilitaires partagés entre cogs."""

import discord
from discord import app_commands


async def handle_app_error(
    interaction: discord.Interaction,
    error: app_commands.AppCommandError,
    *,
    perm_message: str = "Tu n'as pas la permission de faire ça.",
    command_label: str = "une commande",
):
    """Répond TOUJOURS à l'utilisateur, quelle que soit l'erreur, et loggue les cas
    inattendus. Gère aussi bien une interaction déjà déférée qu'une interaction fraîche,
    pour éviter le fameux « The application did not respond »."""
    if isinstance(error, (app_commands.MissingPermissions, app_commands.CheckFailure)):
        message = perm_message
    else:
        original = getattr(error, "original", error)
        if isinstance(original, discord.Forbidden):
            message = "❌ Le bot n'a pas les permissions nécessaires pour faire ça ici."
        else:
            message = f"❌ Une erreur est survenue : {original}"
        print(f"⚠️ Erreur dans {command_label} : {original}")

    try:
        if interaction.response.is_done():
            await interaction.followup.send(message, ephemeral=True)
        else:
            await interaction.response.send_message(message, ephemeral=True)
    except discord.HTTPException:
        pass


async def handle_modal_error(interaction: discord.Interaction, error: Exception, command_label: str = "un formulaire"):
    """Équivalent de handle_app_error pour les erreurs survenant dans Modal.on_submit
    (non interceptées par les .error des app_commands)."""
    original = getattr(error, "original", error)
    if isinstance(original, discord.Forbidden):
        message = "❌ Le bot n'a pas les permissions nécessaires pour faire ça ici."
    else:
        message = f"❌ Une erreur est survenue : {original}"
    print(f"⚠️ Erreur dans {command_label} : {original}")

    try:
        if interaction.response.is_done():
            await interaction.followup.send(message, ephemeral=True)
        else:
            await interaction.response.send_message(message, ephemeral=True)
    except discord.HTTPException:
        pass


class SaphirModal(discord.ui.Modal):
    """Modal de base : garantit qu'une erreur dans on_submit répond toujours à
    l'utilisateur au lieu de laisser Discord afficher « The application did not respond »."""
    error_label = "un formulaire"

    async def on_error(self, interaction: discord.Interaction, error: Exception):
        await handle_modal_error(interaction, error, self.error_label)
