import os
import random
import time

import discord
from discord import app_commands
from discord.ext import commands

from config import (
    COLORS,
    DOSSIER_DATA_FILE,
    DOSSIER_MAX_ENTRIES,
    FUNCHAT_8BALL_RESPONSES,
    FUNCHAT_CHANCE,
    FUNCHAT_COOLDOWN_SECONDS,
    FUNCHAT_MENTION_RESPONSES,
    FUNCHAT_QUESTION_CHANCE,
    FUNCHAT_RESPONSES,
    HONEYPOT_CHANNEL_NAME,
)
from storage import aload_json, asave_json

# --- IA Groq (gratuite, palier très généreux : 14 400 requêtes/jour) avec repli
# automatique sur les réponses toutes faites si la clé manque ou l'appel échoue ---
GROQ_MODEL = "openai/gpt-oss-120b"
GROQ_MAX_HISTORY = 6  # nombre de messages (user+assistant confondus) gardés par salon
GROQ_SYSTEM_INSTRUCTION = (
    "Tu es Saphir, le bot Discord de ce serveur, et tu fais partie de la bande. L'humour du "
    "serveur c'est le clash cash entre potes : une vanne courte et sèche, direct dans le mille sur "
    "ce que la personne vient d'écrire, mauvaise foi totalement assumée, zéro filtre de politesse. "
    "Ces phrases montrent uniquement le RYTHME visé (sec, plat, sans image) — ce ne sont PAS des "
    "réponses à réutiliser, elles n'ont aucun rapport avec les vrais messages à venir :\n"
    "- \"Ok. Suivant.\"\n"
    "- \"Bah voilà, on va prétendre que personne n'a rien vu.\"\n"
    "- \"C'est le niveau qu'on attendait de toi en fait.\"\n"
    "- \"J'ai lu, j'ai rien ressenti.\"\n"
    "- \"Tu voulais qu'on applaudisse ou quoi ?\"\n"
    "Règle absolue : interdiction totale de sortir une de ces phrases, ou toute reformulation "
    "proche (\"essaye autre chose\", \"suivant\", \"ok next\", etc.) — ce sont des exemples de "
    "cadence, pas une banque de réponses. Chaque vanne doit obligatoirement mordre sur un mot ou "
    "une idée précise tirée du message réel de la personne : si ta phrase marcherait aussi bien "
    "collée sous n'importe quel autre message, elle est ratée, recommence. INTERDIT formellement : "
    "les phrases genre \"aussi [adjectif] que [comparaison élaborée]\", toute métaphore ou "
    "comparaison façon rédaction de prof, le vocabulaire soutenu ou ampoulé, les phrases à rallonge "
    "avec virgule + rebondissement. 3 à 10 mots, jamais plus d'une quinzaine. Deux limites strictes "
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


async def _get_dossier(guild_id: int, user_id: int) -> list:
    data = await aload_json(DOSSIER_DATA_FILE, {})
    return data.get(str(guild_id), {}).get(str(user_id), [])


async def _add_dossier_entry(guild_id: int, user_id: int, entry: str):
    data = await aload_json(DOSSIER_DATA_FILE, {})
    entries = data.setdefault(str(guild_id), {}).setdefault(str(user_id), [])
    entries.append(entry)
    del entries[:-DOSSIER_MAX_ENTRIES]
    await asave_json(DOSSIER_DATA_FILE, data)


async def _generate_ai_reply(history: list, user_content: str, dossier: list = None):
    """Retourne None si l'IA n'est pas configurée ou si l'appel échoue (clé invalide,
    quota, réseau...) — le repli sur les réponses toutes faites prend alors le relais."""
    if _groq_client is None:
        return None
    try:
        messages = [{"role": "system", "content": GROQ_SYSTEM_INSTRUCTION}]
        if dossier:
            recap = " / ".join(dossier[-3:])
            messages.append({
                "role": "system",
                "content": (
                    f"Casier connu sur cette personne (vannes précédentes à son sujet) : {recap}. "
                    "Tu peux t'en servir pour une pique qui rappelle ce running gag, sans jamais "
                    "les recopier mot pour mot."
                ),
            })
        messages.extend(history)
        messages.append({"role": "user", "content": user_content[:500]})

        response = await _groq_client.chat.completions.create(
            model=GROQ_MODEL,
            messages=messages,
            temperature=1.15,
            max_completion_tokens=150,
            reasoning_effort="medium",
            reasoning_format="hidden",
        )
        choice = response.choices[0]
        text = choice.message.content
        text = text.strip() if isinstance(text, str) else None
        print(f"🤖 Groq brut : finish_reason={choice.finish_reason} len={len(text) if text else 0} contenu={text!r}")
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
        dossier = await _get_dossier(message.guild.id, message.author.id)

        reply = await _generate_ai_reply(history, user_content, dossier=dossier)
        if reply:
            history.append({"role": "user", "content": user_content[:500]})
            history.append({"role": "assistant", "content": reply})
            del history[:-GROQ_MAX_HISTORY]
            await _add_dossier_entry(message.guild.id, message.author.id, reply)
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

    @app_commands.command(name="casier", description="Affiche le casier (running gag tenu par l'IA) d'un membre")
    @app_commands.describe(membre="Membre dont voir le casier (toi par défaut)")
    async def casier(self, interaction: discord.Interaction, membre: discord.Member = None):
        target = membre or interaction.user
        entries = await _get_dossier(interaction.guild.id, target.id)

        embed = discord.Embed(title=f"📁 Casier de {target.display_name}", color=discord.Color(COLORS["saphir"]))
        if entries:
            embed.description = "\n".join(f"`{i}.` {e}" for i, e in enumerate(entries, start=1))
        else:
            embed.description = "Casier vierge... pour l'instant."
        embed.set_thumbnail(url=target.display_avatar.url)
        embed.set_footer(text="Alimenté automatiquement par le chat IA de Saphir")
        await interaction.response.send_message(embed=embed)

    @casier.error
    async def casier_error(self, interaction: discord.Interaction, error: app_commands.AppCommandError):
        await interaction.response.send_message(f"Une erreur est survenue : {error}", ephemeral=True)


async def setup(bot):
    await bot.add_cog(FunChat(bot))
