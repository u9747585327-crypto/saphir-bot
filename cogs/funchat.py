import random
import time

import discord
from discord.ext import commands

from config import (
    FUNCHAT_8BALL_RESPONSES,
    FUNCHAT_CHANCE,
    FUNCHAT_COOLDOWN_SECONDS,
    FUNCHAT_MENTION_RESPONSES,
    FUNCHAT_QUESTION_CHANCE,
    FUNCHAT_RESPONSES,
    HONEYPOT_CHANNEL_NAME,
)


class FunChat(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.last_reply = {}

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot or not message.guild:
            return

        if message.channel.name == HONEYPOT_CHANNEL_NAME:
            return

        content = message.content.strip()
        if not content:
            return

        # mentionner le bot déclenche toujours une réponse, sans cooldown
        if self.bot.user in message.mentions:
            try:
                await message.reply(random.choice(FUNCHAT_MENTION_RESPONSES), mention_author=False)
            except discord.HTTPException:
                pass
            return

        now = time.time()
        if now - self.last_reply.get(message.channel.id, 0) < FUNCHAT_COOLDOWN_SECONDS:
            return

        if content.endswith("?") and random.random() < FUNCHAT_QUESTION_CHANCE:
            self.last_reply[message.channel.id] = now
            try:
                await message.reply(random.choice(FUNCHAT_8BALL_RESPONSES), mention_author=False)
            except discord.HTTPException:
                pass
            return

        if random.random() < FUNCHAT_CHANCE:
            self.last_reply[message.channel.id] = now
            try:
                await message.reply(random.choice(FUNCHAT_RESPONSES), mention_author=False)
            except discord.HTTPException:
                pass


async def setup(bot):
    await bot.add_cog(FunChat(bot))
