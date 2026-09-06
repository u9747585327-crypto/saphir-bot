import asyncio
import os
import sys

import discord
from discord.ext import commands
from dotenv import load_dotenv

from config import BOT_NAME
from keep_alive import keep_alive

# sur Render (et tout environnement sans vrai terminal), stdout est bufferisé par
# défaut : les print() restent coincés en mémoire au lieu de s'afficher tout de
# suite dans les logs. Le mode ligne par ligne force l'affichage immédiat.
sys.stdout.reconfigure(line_buffering=True)

load_dotenv()
TOKEN = os.getenv("DISCORD_TOKEN")

intents = discord.Intents.default()
intents.members = True
intents.message_content = True

bot = commands.Bot(command_prefix="+", intents=intents, help_command=None)

INITIAL_COGS = [
    "cogs.scan",
    "cogs.autorole",
    "cogs.voicerole",
    "cogs.voicehub",
    "cogs.bringall",
    "cogs.honeypot",
    "cogs.prison",
    "cogs.logs",
    "cogs.leveling",
    "cogs.hierarchy",
    "cogs.moderation",
    "cogs.broadcast",
    "cogs.funchat",
    "cogs.diagnostic",
    "cogs.osint",
    "cogs.help",
]


async def _sync_all(guild=None):
    """Copie les commandes vers un serveur précis (ou tous ceux déjà rejoints), puis
    vide la liste globale côté Discord. On ne synchronise plus jamais en global : avoir
    à la fois des commandes globales ET des commandes par serveur fait que Discord les
    affiche en double dans un même serveur."""
    guilds = [guild] if guild else bot.guilds
    for g in guilds:
        bot.tree.copy_global_to(guild=g)
        synced = await bot.tree.sync(guild=g)
        print(f"{len(synced)} commande(s) synchronisée(s) sur {g.name}")

    bot.tree.clear_commands(guild=None)
    await bot.tree.sync()


@bot.event
async def on_ready():
    print(f"💎 {BOT_NAME} connecté en tant que {bot.user} (ID: {bot.user.id})")
    try:
        await _sync_all()
    except Exception as e:
        print(f"Erreur de synchronisation des commandes : {e}")


@bot.event
async def on_guild_join(guild: discord.Guild):
    try:
        await _sync_all(guild)
    except Exception as e:
        print(f"Erreur de synchronisation des commandes sur {guild.name} : {e}")


async def main():
    if not TOKEN:
        raise SystemExit("DISCORD_TOKEN manquant dans le fichier .env")
    async with bot:
        for cog in INITIAL_COGS:
            await bot.load_extension(cog)
        await bot.start(TOKEN)


if __name__ == "__main__":
    keep_alive()
    asyncio.run(main())
