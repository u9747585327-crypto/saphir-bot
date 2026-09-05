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

# --- IA Groq (gratuite, palier très généreux : 14 400 requêtes/jour) avec repli
# automatique sur les réponses toutes faites si la clé manque ou l'appel échoue ---
GROQ_MODEL = "openai/gpt-oss-120b"
GROQ_MAX_HISTORY = 6  # nombre de messages (user+assistant confondus) gardés par salon
GROQ_SYSTEM_INSTRUCTION = (
    "Tu es Saphir, le bot Discord de ce serveur, et tu fais partie de la bande. L'humour du "
    "serveur c'est le clash cash entre potes : une vanne courte et mordante, direct dans le mille "
    "sur ce que la personne vient d'écrire, mauvaise foi totalement assumée, zéro filtre de "
    "politesse. Pense réaction Discord/Twitter, pas dissertation : 3 à 10 mots, jamais plus d'une "
    "quinzaine. INTERDIT : les phrases construites genre \"aussi [adjectif] que [comparaison "
    "élaborée]\", les métaphores façon rédaction de prof, le vocabulaire soutenu ou ampoulé, les "
    "phrases à rallonge avec virgule + rebondissement. Écris comme un pote qui tape vite sur son "
    "clavier, pas comme quelqu'un qui a réfléchi dix minutes à sa punchline. Deux limites strictes "
    "uniquement : jamais d'insulte à caractère raciste, sexiste, homophobe ou discriminatoire, et "
    "jamais d'acharnement répété sur la même personne. Tu ne rebondis jamais sur des propos "
    "réellement haineux, violents ou explicites (tu recadres sèchement à la place, en aussi court). "
    "Réponds TOUJOURS en français, en une seule phrase courte, jamais coupée, ton cash et familier, "
    "zéro conseil sérieux, zéro blabla. Tu te souviens de ce qui vient d'être dit dans la "
    "conversation et tu peux enchaîner dessus."
)

_GROQ_API_KEY = os.environ.get("GROQ_API_KEY")
_groq_client = None

if _GROQ_API_KEY:
    try:
        from groq import AsyncGroq

        _groq_client = AsyncGroq(api_key=_GROQ_API_KEY)
        print("🤖 FunChat : IA Groq activée")
    except Exception as e:
        print(f"⚠️ GROQ_API_KEY fourni mais initialisation impossible ({e}) — repli sur les réponses toutes faites")
        _groq_client = None


def is_ai_enabled() -> bool:
    return _groq_client is not None


async def _generate_ai_reply(history: list, user_content: str):
    """Retourne None si l'IA n'est pas configurée ou si l'appel échoue (clé invalide,
    quota, réseau...) — le repli sur les réponses toutes faites prend alors le relais."""
    if _groq_client is None:
        return None
    try:
        messages = [{"role": "system", "content": GROQ_SYSTEM_INSTRUCTION}]
        messages.extend(history)
        messages.append({"role": "user", "content": user_content[:500]})

        response = await _groq_client.chat.completions.create(
            model=GROQ_MODEL,
            messages=messages,
            temperature=1.05,
            max_tokens=60,
        )
        text = response.choices[0].message.content
        text = text.strip() if isinstance(text, str) else None
        return text[:300] if text else None
    except Exception as e:
        print(f"⚠️ Erreur Groq : {e}")
        return None


class FunChat(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.last_reply = {}
        self.history = {}

    async def _reply(self, message: discord.Message, fallback_pool: list):
        channel_id = message.channel.id
        history = self.history.setdefault(channel_id, [])
        user_content = message.content.strip()

        reply = await _generate_ai_reply(history, user_content)
        if reply:
            history.append({"role": "user", "content": user_content[:500]})
            history.append({"role": "assistant", "content": reply})
            del history[:-GROQ_MAX_HISTORY]
        else:
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
