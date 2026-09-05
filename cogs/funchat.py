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

# --- IA Mistral (gratuite, entreprise française — pas de blocage régional UE) avec
# repli automatique sur les réponses toutes faites si la clé manque ou l'appel échoue ---
MISTRAL_MODEL = "mistral-small-latest"
MISTRAL_SYSTEM_INSTRUCTION = (
    "Tu es Saphir, le bot Discord de ce serveur. Ton ton est insolent, sarcastique et "
    "drôle, un peu provocateur mais jamais méchant, jamais offensant, et tu ne rebondis "
    "jamais sur des propos haineux, violents ou explicites (tu ignores ou recadres "
    "gentiment à la place). Tu réponds toujours en français, en une phrase courte "
    "maximum deux, ton familier, jamais de blabla ni de politesse excessive. Pas de "
    "conseils sérieux, pas d'infos factuelles longues : tu es juste là pour vanner "
    "gentiment la conversation."
)

_MISTRAL_API_KEY = os.environ.get("MISTRAL_API_KEY")
_mistral_client = None

if _MISTRAL_API_KEY:
    try:
        from mistralai.client import Mistral

        _mistral_client = Mistral(api_key=_MISTRAL_API_KEY)
        print("🤖 FunChat : IA Mistral activée")
    except Exception as e:
        print(f"⚠️ MISTRAL_API_KEY fourni mais initialisation impossible ({e}) — repli sur les réponses toutes faites")
        _mistral_client = None


def is_ai_enabled() -> bool:
    return _mistral_client is not None


async def _generate_ai_reply(user_message: str):
    """Retourne None si l'IA n'est pas configurée ou si l'appel échoue (clé invalide,
    quota, réseau...) — le repli sur les réponses toutes faites prend alors le relais."""
    if _mistral_client is None:
        return None
    try:
        response = await _mistral_client.chat.complete_async(
            model=MISTRAL_MODEL,
            messages=[
                {"role": "system", "content": MISTRAL_SYSTEM_INSTRUCTION},
                {"role": "user", "content": user_message[:500]},
            ],
            temperature=1.0,
            max_tokens=120,
        )
        text = response.choices[0].message.content
        text = text.strip() if isinstance(text, str) else None
        return text[:1900] if text else None
    except Exception as e:
        print(f"⚠️ Erreur Mistral : {e}")
        return None


class FunChat(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.last_reply = {}

    async def _reply(self, message: discord.Message, fallback_pool: list):
        reply = await _generate_ai_reply(message.content.strip())
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
