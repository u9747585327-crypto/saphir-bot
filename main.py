import asyncio
import os

import discord
from discord.ext import commands
from dotenv import load_dotenv

from config import BOT_NAME
from keep_alive import keep_alive

load_dotenv()
TOKEN = os.getenv("DISCORD_TOKEN")

intents = discord.Intents.default()
intents.members = True
intents.message_content = True

bot = commands.Bot(command_prefix="!", intents=intents, help_command=None)

INITIAL_COGS = [
    "cogs.scan",
    "cogs.autorole",
    "cogs.voicerole",
    "cogs.bringall",
    "cogs.honeypot",
    "cogs.prison",
]


@bot.event
async def on_ready():
    print(f"💎 {BOT_NAME} connecté en tant que {bot.user} (ID: {bot.user.id})")
    try:
        synced = await bot.tree.sync()
        print(f"{len(synced)} commande(s) slash synchronisée(s)")
    except Exception as e:
        print(f"Erreur de synchronisation des commandes : {e}")


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
