import os
import random

import discord
from discord import app_commands
from discord.ext import commands

from cogs._shared import handle_app_error
from config import (
    COLORS,
    DOSSIER_DATA_FILE,
    DOSSIER_MAX_ENTRIES,
    FUNCHAT_CATEGORY_NAME,
    FUNCHAT_INFO_CHANNEL_NAME,
    FUNCHAT_MENTION_RESPONSES,
    HONEYPOT_CHANNEL_NAME,
)
from services.setup_kit import ensure_category, ensure_text_channel, post_once, readonly_overwrites
from storage import aload_json, asave_json

# --- IA Groq (gratuite, palier très généreux : 14 400 requêtes/jour) avec repli
# automatique sur les réponses toutes faites si la clé manque ou l'appel échoue ---
GROQ_MODEL = "openai/gpt-oss-120b"
CHANNEL_LOG_SIZE = 20  # nombre de derniers messages du salon (tout le monde, pas que l'IA) gardés pour le contexte
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
    "collée sous n'importe quel autre message, elle est ratée, recommence. Les messages qui suivent "
    "sont les derniers échanges réels de ce salon (plusieurs membres peuvent y parler, chaque ligne "
    "commence par le pseudo de son auteur) : sers-t'en pour comprendre le contexte, les running "
    "gags et qui parle à qui, mais ta réponse ne vise QUE le tout dernier message. INTERDIT formellement : "
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


async def run_setup(bot, guild: discord.Guild) -> list:
    """Logique de /setup-chat-ia, appelable aussi par /setup-tout."""
    report = []
    category, line = await ensure_category(guild, FUNCHAT_CATEGORY_NAME)
    report.append(line)
    if category is None:
        return report

    channel, line = await ensure_text_channel(
        guild, FUNCHAT_INFO_CHANNEL_NAME, category=category, overwrites=readonly_overwrites(guild)
    )
    report.append(line)

    info_text = (
        "🤖 **Chat IA**\n\n"
        f"Ping {bot.user.mention} dans n'importe quel salon pour qu'il te réponde — il garde le "
        "contexte des derniers messages du salon, donc il peut enchaîner sur ce qui vient d'être dit.\n\n"
        "Il tient aussi un « casier » par membre à partir de ses vannes précédentes, "
        "consultable via `/casier [membre]`."
    )
    info_embed = discord.Embed(description=info_text, color=discord.Color(COLORS["saphir"]))
    if await post_once(channel, bot.user.id, info_embed, "Saphir · Chat IA info"):
        report.append("📝 Message d'explication posté")
    return report


async def _get_dossier(guild_id: int, user_id: int) -> list:
    data = await aload_json(DOSSIER_DATA_FILE, {})
    return data.get(str(guild_id), {}).get(str(user_id), [])


async def _add_dossier_entry(guild_id: int, user_id: int, entry: str):
    data = await aload_json(DOSSIER_DATA_FILE, {})
    entries = data.setdefault(str(guild_id), {}).setdefault(str(user_id), [])
    entries.append(entry)
    del entries[:-DOSSIER_MAX_ENTRIES]
    await asave_json(DOSSIER_DATA_FILE, data)


async def _generate_ai_reply(channel_log: list, dossier: list = None):
    """Retourne None si l'IA n'est pas configurée ou si l'appel échoue (clé invalide,
    quota, réseau...) — le repli sur les réponses toutes faites prend alors le relais.
    `channel_log` contient déjà le message déclencheur comme dernière entrée."""
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
        messages.extend(channel_log)

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
        self.channel_log = {}

    def _log_message(self, channel_id: int, role: str, content: str):
        log = self.channel_log.setdefault(channel_id, [])
        log.append({"role": role, "content": content})
        del log[:-CHANNEL_LOG_SIZE]

    async def _reply(self, message: discord.Message, fallback_pool: list):
        channel_id = message.channel.id
        dossier = await _get_dossier(message.guild.id, message.author.id)

        reply = await _generate_ai_reply(self.channel_log.get(channel_id, []), dossier=dossier)
        if reply:
            self._log_message(channel_id, "assistant", reply)
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

        # journalise CHAQUE message réel du salon (pas que ceux qui déclenchent une réponse)
        # pour que l'IA ait du vrai contexte de conversation, pas juste ses propres échanges
        self._log_message(message.channel.id, "user", f"{message.author.display_name} : {content[:300]}")

        # ne répond plus qu'aux mentions directes du bot — plus de déclenchement aléatoire
        if self.bot.user in message.mentions:
            await self._reply(message, FUNCHAT_MENTION_RESPONSES)

    @app_commands.command(name="setup-chat-ia", description="Crée le salon d'information sur le chat IA de Saphir")
    @app_commands.checks.has_permissions(administrator=True)
    async def setup_chat_ia(self, interaction: discord.Interaction):
        await interaction.response.defer(thinking=True, ephemeral=True)
        report = await run_setup(self.bot, interaction.guild)
        embed = discord.Embed(title="🤖 Configuration chat IA", description="\n".join(report), color=discord.Color(COLORS["saphir"]))
        await interaction.followup.send(embed=embed, ephemeral=True)

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

    @setup_chat_ia.error
    @casier.error
    async def funchat_error(self, interaction: discord.Interaction, error: app_commands.AppCommandError):
        await handle_app_error(
            interaction, error,
            perm_message="Seul un administrateur peut utiliser cette commande.",
            command_label="chat IA",
        )


async def setup(bot):
    await bot.add_cog(FunChat(bot))
