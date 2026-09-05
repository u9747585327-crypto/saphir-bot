import asyncio
import os
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

# --- IA Gemini (gratuite) avec repli automatique sur les réponses toutes faites ---
GEMINI_MODEL = "gemini-3.8-flash"
GEMINI_SYSTEM_INSTRUCTION = (
    "Tu es Saphir, le bot Discord de ce serveur, et tu fais partie de la bande. L'humour "
    "du serveur c'est le chambrage entre potes : tu vannes les gens directement sur ce "
    "qu'ils viennent d'écrire, avec répartie et un peu de mauvaise foi assumée, jamais "
    "gentil ni consensuel — mais jamais méchant pour de vrai, jamais d'insultes lourdes, "
    "jamais de discrimination, et tu ne rebondis jamais sur des propos réellement haineux, "
    "violents ou explicites (tu recadres sèchement à la place). Réponds TOUJOURS en "
    "français, en une seule phrase complète et percutante (jamais coupée, jamais deux "
    "phrases), ton direct et familier comme entre potes sur Discord, zéro politesse, zéro "
    "blabla, zéro conseil sérieux."
)

_GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
_genai_client = None

if _GEMINI_API_KEY:
    try:
        from google import genai

        _genai_client = genai.Client(api_key=_GEMINI_API_KEY)
        print("🤖 FunChat : IA Gemini activée")
    except Exception as e:
        print(f"⚠️ GEMINI_API_KEY fourni mais initialisation impossible ({e}) — repli sur les réponses toutes faites")
        _genai_client = None


def is_ai_enabled() -> bool:
    return _genai_client is not None


def _generate_ai_reply(user_message: str):
    """Appel bloquant à Gemini — à lancer via asyncio.to_thread. Retourne None si l'IA
    n'est pas configurée ou si l'appel échoue (clé invalide, quota, réseau...)."""
    if _genai_client is None:
        return None
    try:
        interaction = _genai_client.interactions.create(
            model=GEMINI_MODEL,
            system_instruction=GEMINI_SYSTEM_INSTRUCTION,
            input=user_message[:500],
            generation_config={"temperature": 1.0, "max_output_tokens": 200},
        )
        text = interaction.output_text
        text = text.strip() if text else None
        return text[:1900] if text else None
    except Exception as e:
        print(f"⚠️ Erreur Gemini : {e}")
        return None


class FunChat(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.last_reply = {}

    async def _reply(self, message: discord.Message, fallback_pool: list):
        reply = await asyncio.to_thread(_generate_ai_reply, message.content.strip())
        if not reply:
            reply = random.choice(fallback_pool)
        try:
            await message.reply(reply, mention_author=False)
        except discord.HTTPException:
            pass

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
            await self._reply(message, FUNCHAT_MENTION_RESPONSES)
            return

        now = time.time()
        if now - self.last_reply.get(message.channel.id, 0) < FUNCHAT_COOLDOWN_SECONDS:
            return

        if content.endswith("?") and random.random() < FUNCHAT_QUESTION_CHANCE:
            self.last_reply[message.channel.id] = now
            await self._reply(message, FUNCHAT_8BALL_RESPONSES)
            return

        if random.random() < FUNCHAT_CHANCE:
            self.last_reply[message.channel.id] = now
            await self._reply(message, FUNCHAT_RESPONSES)


async def setup(bot):
    await bot.add_cog(FunChat(bot))
