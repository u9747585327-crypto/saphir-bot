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
    FUNCHAT_MENTION_RESPONSES,
    HONEYPOT_CHANNEL_NAME,
)
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


# Pas de commande /setup-* ici : le chat IA n'a aucun salon dédié. Il répond quand on
# ping le bot, dans n'importe quel salon, et /casier se consulte de partout.


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


# --- Répartie quand on embête Saphir : ping, spam de pings, clash -----------------
# {nom} = pseudo de la personne, {n} = nombre de pings récents. Ton sec, sarcastique,
# jamais d'insulte discriminatoire.

FENETRE_SPAM = 40           # s : on compte les pings sur cette fenêtre
SEUIL_SPAM = 3              # à partir de là, c'est du spam
SEUIL_BOUDE = 6             # et là, Saphir arrête de répondre
DUREE_BOUDE = 180

REPARTIE_PING = [
    "Oui {nom}. Je t'écoute. Malheureusement.",
    "Tu m'as pingé. Je suis venu. On est tous les deux déçus.",
    "Présent. Pas ravi, mais présent.",
    "Quoi ? T'as encore besoin d'attention ?",
    "Je suis un bot, {nom}. Même moi j'ai mieux à faire.",
    "Si c'est pour dire bonjour, c'est non.",
    "J'étais bien, là. Avant.",
    "On m'a codé pour répondre. Pas pour apprécier.",
    "Vas-y, balance. Je ferai semblant d'être intéressé.",
    "Encore toi. Évidemment.",
    "Tu sais que je n'ai pas le choix de lire tes messages ? C'est ça le pire.",
    "Je te réponds uniquement parce que mon code m'y oblige.",
]

REPARTIE_SPAM = [   # du plus calme au plus agacé : on avance avec le nombre de pings
    "{n} pings, {nom}. Tu veux que je t'adopte ?",
    "Oui, j'ai vu. Les {n} fois.",
    "Ping numéro {n}. Le record du serveur est en danger.",
    "{nom}, tu pings comme on appuie sur le bouton d'un ascenseur. Ça va pas plus vite.",
    "À ce rythme, c'est plus une conversation, c'est une prise d'otage.",
    "Je suis un bot, pas ton psy. {n} pings, quand même.",
]

REPARTIE_BOUDE = [
    "{n} pings. Je ne te réponds plus pendant 3 minutes. Profite du silence, c'est ce que tu mérites.",
    "Terminé. Je te mets en sourdine dans ma tête pour 3 minutes, {nom}.",
    "Bravo {nom}, t'as réussi à saouler un programme. Je boude. 3 minutes.",
]

REPARTIE_CLASH = [
    "Tu clashes un bot, {nom}. Pense à ce que ça dit de ta journée.",
    "Dit celui qui parle à un bot à cette heure-ci.",
    "J'ai pas d'émotions, {nom}. Donc là, c'est juste toi qui t'énerves tout seul.",
    "C'est mignon. T'as dû y réfléchir longtemps.",
    "Je suis du code et j'ai quand même plus de répartie que toi.",
    "Venant de toi, je le prends presque comme un compliment.",
    "Je te bloquerais bien, mais on m'a pas donné le bouton.",
    "Note pour plus tard : {nom} perd ses débats contre un bot.",
    "Insulte reçue, analysée, classée sans suite.",
    "Je peux pas me vexer, j'ai pas d'ego. Toi par contre, ça se voit que si.",
    "T'as tapé ça avec tes deux doigts, je suis touché.",
    "Pas mal. Maintenant essaie sur quelqu'un qui peut répondre avec une vraie main.",
]

# mots qui font d'un ping un clash ; repérés en mot entier, sans accents ni majuscules
MOTS_CLASH = {
    "nul", "nulle", "naze", "con", "conne", "connard", "connasse", "debile", "idiot", "idiote",
    "abruti", "bouffon", "clown", "clochard", "fdp", "ntm", "tg", "ftg", "pute", "merde", "merdique",
    "inutile", "guignol", "tocard", "batard", "enfoire", "cretin", "imbecile", "boloss", "bolosse",
    "victime", "golmon", "teubé", "teube", "cheh", "nullos", "pourri", "claque", "eclate",
}


def _normaliser(texte: str) -> str:
    import unicodedata
    texte = unicodedata.normalize("NFD", texte.lower())
    return "".join(c for c in texte if unicodedata.category(c) != "Mn")


def est_un_clash(texte: str) -> bool:
    import re
    mots = re.findall(r"[a-z]+", _normaliser(texte))
    return any(m in MOTS_CLASH or _normaliser(m) in MOTS_CLASH for m in mots)


class FunChat(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.channel_log = {}
        self._pings = {}        # user_id -> horodatages (monotonic) des pings récents
        self._boude = {}        # user_id -> monotonic() jusqu'auquel Saphir l'ignore

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
            reply = random.choice(fallback_pool).format(nom=message.author.display_name, n=1)

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
            await self._repartie(message)

    async def _repartie(self, message: discord.Message):
        """Ping simple : vanne. Pings en rafale : agacement croissant, puis Saphir boude
        3 min (et ne répond plus du tout, ce qui coupe aussi le spam). Clash : il renvoie."""
        import time
        uid, maintenant = message.author.id, time.monotonic()
        if self._boude.get(uid, 0) > maintenant:
            return
        # plusieurs @Saphir dans un seul message comptent chacun
        nb = max(1, message.content.count(f"<@{self.bot.user.id}>") + message.content.count(f"<@!{self.bot.user.id}>"))
        recents = [t for t in self._pings.get(uid, []) if maintenant - t < FENETRE_SPAM] + [maintenant] * nb
        self._pings[uid] = recents
        n, nom = len(recents), message.author.display_name

        if n >= SEUIL_BOUDE:
            self._boude[uid] = maintenant + DUREE_BOUDE
            self._pings.pop(uid, None)
            texte = random.choice(REPARTIE_BOUDE)
        elif n >= SEUIL_SPAM:
            # on avance dans la liste avec le nombre de pings, avec un peu de hasard
            i = min(len(REPARTIE_SPAM) - 1, (n - SEUIL_SPAM) * 2 + random.randint(0, 1))
            texte = REPARTIE_SPAM[i]
        elif est_un_clash(message.content):
            if is_ai_enabled():
                await self._reply(message, REPARTIE_CLASH)
                return
            texte = random.choice(REPARTIE_CLASH)
        else:
            if is_ai_enabled():
                await self._reply(message, REPARTIE_PING)
                return
            texte = random.choice(REPARTIE_PING + FUNCHAT_MENTION_RESPONSES)
        try:
            await message.reply(texte.format(nom=nom, n=n), mention_author=False)
        except discord.HTTPException:
            pass

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
    async def funchat_error(self, interaction: discord.Interaction, error: app_commands.AppCommandError):
        await handle_app_error(interaction, error, command_label="casier")


async def setup(bot):
    await bot.add_cog(FunChat(bot))
