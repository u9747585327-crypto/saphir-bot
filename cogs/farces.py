"""
cogs/farces.py
Commandes pour embêter gentiment les membres, en texte et en vocal.

Texte : /hack, /fakeban, /perroquet, /surnom.
Vocal : /bruitage, /prout, /annonce-vocale, /kidnapping (staff).

Les sons et les annonces (voix « Léo », ElevenLabs) sont générés une fois pour toutes
et livrés dans assets/farces : rien n'est appelé en ligne.

Garde-fous, pour que ça reste une blague et pas du harcèlement :
- /pas-touche : n'importe qui peut refuser d'être visé (bascule, mémorisée) ;
- délais : une farce texte toutes les 10 s et une vocale toutes les 15 s par membre
  (le staff en est dispensé), et une même cible n'est pas visée deux fois en 30 s ;
- les bots ne sont jamais visés ;
- en vocal, il faut être soi-même dans le salon, et un son ne coupe jamais Saphir Radio ;
- /perroquet ne mentionne personne en répétant (pas de ping en boucle) ;
- /surnom rend le pseudo d'origine au bout de 10 min, même après un redémarrage ;
- /kidnapping est réservé à ceux qui ont le droit de déplacer des membres.
"""

import asyncio
import os
import random
import time

import discord
from discord import app_commands
from discord.ext import commands, tasks

from cogs._shared import handle_app_error
from config import COLORS, GUILD_SETTINGS_FILE
from storage import aload_json, asave_json

FARCES_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "assets", "farces")

DELAI_TEXTE = 10
DELAI_VOCAL = 15
DELAI_CIBLE = 30          # protège la victime : le staff n'en est pas dispensé
DUREE_SURNOM = 600
DUREE_PERROQUET = 60
REPETITIONS_PERROQUET = 6
DUREE_KIDNAPPING = 15

BRUITAGES = {
    "pet": "💨 Pet",
    "klaxon": "📯 Klaxon",
    "rires": "😂 Rires enregistrés",
    "trombone": "🎺 Trombone triste",
    "suspense": "😱 Suspense",
    "criquets": "🦗 Criquets (silence gênant)",
    "applaudissements": "👏 Applaudissements",
}

MOTS_DE_PASSE = ["jaimelespates123", "azerty", "motdepasse", "MaMamanEstLaMeilleure", "1234 (même pas 12345)",
                 "nutella4ever", "j3suisunh4ck3r", "soleil", "chaton2009"]
RECHERCHES = ["comment devenir drôle", "pourquoi personne me répond sur discord",
              "est-ce que les pâtes c'est un légume", "comment gagner en ranked sans jouer",
              "tuto avoir des amis", "mon chat me juge est-ce normal", "comment parler aux filles tuto",
              "c'est grave de dormir 14h", "acheter des abonnés pas cher"]
BUTINS = ["37 photos de son chat", "un dossier « devoirs » qui ne contient pas de devoirs",
          "4 Go de mèmes de 2016", "ses brouillons de messages jamais envoyés", "une playlist 100 % Jul",
          "son classement en ranked (on préfère ne pas en parler)"]
FINS_HACK = ["Hack terminé. Les données ont été envoyées à sa mère. 📨",
             "Hack terminé. Résultat : rien d'intéressant, comme prévu.",
             "Hack terminé. On a tout supprimé sauf ses mèmes, on n'est pas des monstres.",
             "Hack terminé. Son PC a demandé à être débranché."]
RAISONS_BAN = ["trop nul en ranked", "a dit « quoi » et on a répondu « feur »",
               "odeur suspecte détectée à travers le micro", "a liké son propre message",
               "abus de « mdr » sans jamais rire", "a mis de l'ananas sur la pizza",
               "respire trop fort dans le vocal", "AFK depuis 2019"]
SURNOMS = ["Le Boulet", "Monsieur Wifi Coupé", "Roi du Malaise", "Pâte Trop Cuite", "Le Stagiaire",
           "Micro Ouvert", "0 Kill 12 Morts", "Champion de l'AFK", "Bot Humain", "Chef des Bugs",
           "Toujours En Retard", "Spécialiste du Vu"]


def moquer(texte: str) -> str:
    """mOdE mOqUeUr : une lettre sur deux en majuscule."""
    sortie, maj = [], False
    for c in texte:
        if c.isalpha():
            sortie.append(c.upper() if maj else c.lower())
            maj = not maj
        else:
            sortie.append(c)
    return "".join(sortie)


def fichier_au_hasard(dossier: str):
    chemin = os.path.join(FARCES_DIR, dossier)
    try:
        fichiers = [f for f in os.listdir(chemin) if f.endswith(".ogg")]
    except FileNotFoundError:
        return None
    return os.path.join(chemin, random.choice(fichiers)) if fichiers else None


class Farces(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self._dernier = {}          # (type, id) -> monotonic() de la dernière farce
        self._perroquets = {}       # (guild_id, cible_id) -> {salon, fin, restant}
        self.restaurer_surnoms.start()

    async def cog_unload(self):
        self.restaurer_surnoms.cancel()

    # ── garde-fous ───────────────────────────────────────────────────────────

    def _attente(self, cle, duree) -> float:
        d = self._dernier.get(cle)
        return 0 if d is None else max(0.0, duree - (time.monotonic() - d))

    async def _refus(self, guild_id: int) -> list:
        settings = await aload_json(GUILD_SETTINGS_FILE, {})
        return settings.get(str(guild_id), {}).get("farces_refus", [])

    async def _peut(self, interaction: discord.Interaction, cible: discord.Member = None, vocal=False) -> bool:
        """Vérifie délais, refus et cible ; répond lui-même en cas de refus."""
        async def non(texte):
            await interaction.response.send_message(texte, ephemeral=True)
            return False

        # le délai du lanceur sert à éviter le spam ; le staff (admin, gestion du serveur)
        # en est dispensé. Les protections de la cible, elles, s'appliquent à tous.
        droits = interaction.user.guild_permissions
        staff = droits.administrator or droits.manage_guild
        delai = DELAI_VOCAL if vocal else DELAI_TEXTE
        attente = 0 if staff else self._attente(("lanceur", interaction.user.id), delai)
        if attente:
            return await non(f"⏳ Doucement : prochaine farce dans {attente:.0f} s.")
        if cible is not None:
            if cible.bot:
                return await non("🤖 Saphir ne s'attaque pas à ses collègues robots.")
            if cible.id in await self._refus(interaction.guild.id):
                return await non(f"🛡️ {cible.display_name} a activé `/pas-touche`. On le laisse tranquille.")
            attente = self._attente(("cible", cible.id), DELAI_CIBLE)
            if attente:
                return await non(f"😮‍💨 Laisse {cible.display_name} respirer, il vient déjà de se faire avoir "
                                 f"(encore {attente:.0f} s).")
        self._dernier[("lanceur", interaction.user.id)] = time.monotonic()
        if cible is not None:
            self._dernier[("cible", cible.id)] = time.monotonic()
        return True

    @app_commands.command(name="pas-touche", description="Refuser (ou accepter à nouveau) d'être la cible des farces")
    async def pas_touche(self, interaction: discord.Interaction):
        settings = await aload_json(GUILD_SETTINGS_FILE, {})
        refus = settings.setdefault(str(interaction.guild.id), {}).setdefault("farces_refus", [])
        if interaction.user.id in refus:
            refus.remove(interaction.user.id)
            texte = "🎯 Bouclier retiré : tu peux de nouveau te faire avoir."
        else:
            refus.append(interaction.user.id)
            texte = "🛡️ Bouclier activé : plus aucune farce ne peut te viser. `/pas-touche` pour l'enlever."
        await asave_json(GUILD_SETTINGS_FILE, settings)
        await interaction.response.send_message(texte, ephemeral=True)

    # ── texte ────────────────────────────────────────────────────────────────

    @app_commands.command(name="hack", description="Pirate (pour de faux) un membre, en direct")
    @app_commands.describe(membre="La victime")
    async def hack(self, interaction: discord.Interaction, membre: discord.Member):
        if not await self._peut(interaction, membre):
            return
        lignes = [f"💻 **Piratage de {membre.mention} en cours…**"]
        await interaction.response.send_message("\n".join(lignes))
        etapes = [
            f"🌐 Adresse IP trouvée : `127.0.0.{random.randint(2, 254)}` (oui, c'est chez lui)",
            f"🔑 Mot de passe : `{random.choice(MOTS_DE_PASSE)}`",
            f"🔍 Dernière recherche Google : *« {random.choice(RECHERCHES)} »*",
            f"📂 Fichiers récupérés : {random.choice(BUTINS)}",
            "📤 Envoi de tout ça à sa famille… ✅",
            f"**{random.choice(FINS_HACK)}**",
        ]
        for etape in etapes:
            await asyncio.sleep(1.7)
            lignes.append(etape)
            try:
                await interaction.edit_original_response(content="\n".join(lignes))
            except discord.HTTPException:
                return

    @app_commands.command(name="fakeban", description="Bannit un membre… pour de faux")
    @app_commands.describe(membre="La victime")
    async def fakeban(self, interaction: discord.Interaction, membre: discord.Member):
        if not await self._peut(interaction, membre):
            return
        embed = discord.Embed(
            title="🔨 Bannissement",
            description=f"{membre.mention} a été **banni** du serveur.\n**Raison** : {random.choice(RAISONS_BAN)}",
            color=discord.Color(COLORS["danger"]),
        )
        embed.set_footer(text=f"Par {interaction.user.display_name}")
        await interaction.response.send_message(content=membre.mention, embed=embed)
        await asyncio.sleep(6)
        embed.title = "🔨 Bannissement… ou pas"
        embed.description += "\n\n😭 **C'était une blague.** Pour cette fois."
        embed.color = discord.Color(COLORS["success"])
        try:
            await interaction.edit_original_response(embed=embed)
        except discord.HTTPException:
            pass

    @app_commands.command(name="perroquet", description="Pendant 1 min, Saphir répète ce qu'il écrit en mOdE mOqUeUr")
    @app_commands.describe(membre="La victime")
    async def perroquet(self, interaction: discord.Interaction, membre: discord.Member):
        if not await self._peut(interaction, membre):
            return
        self._perroquets[(interaction.guild.id, membre.id)] = {
            "salon": interaction.channel.id,
            "fin": time.monotonic() + DUREE_PERROQUET,
            "restant": REPETITIONS_PERROQUET,
        }
        await interaction.response.send_message(
            f"🦜 Le perroquet s'est posé sur l'épaule de {membre.mention}. Pendant une minute, "
            "tout ce qu'il écrit ici sera répété… à notre façon."
        )

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.guild is None or message.author.bot or not message.content:
            return
        cle = (message.guild.id, message.author.id)
        p = self._perroquets.get(cle)
        if p is None:
            return
        if time.monotonic() > p["fin"] or p["restant"] <= 0:
            self._perroquets.pop(cle, None)
            return
        if message.channel.id != p["salon"]:
            return
        p["restant"] -= 1
        try:
            await message.reply(f"🦜 {moquer(message.content)[:1800]}", mention_author=False,
                                allowed_mentions=discord.AllowedMentions.none())
        except discord.HTTPException:
            pass

    @app_commands.command(name="surnom", description="Donne un surnom ridicule à un membre pendant 10 min")
    @app_commands.describe(membre="La victime")
    async def surnom(self, interaction: discord.Interaction, membre: discord.Member):
        guild = interaction.guild
        if membre == guild.owner or membre.top_role >= guild.me.top_role:
            await interaction.response.send_message(
                f"👑 {membre.display_name} est trop haut placé, Discord m'interdit de le renommer.", ephemeral=True)
            return
        if not guild.me.guild_permissions.manage_nicknames:
            await interaction.response.send_message("❌ Il me manque la permission « Gérer les pseudos ».", ephemeral=True)
            return
        settings = await aload_json(GUILD_SETTINGS_FILE, {})
        en_cours = settings.setdefault(str(guild.id), {}).setdefault("farces_surnoms", {})
        if str(membre.id) in en_cours:
            await interaction.response.send_message(f"🏷️ {membre.display_name} porte déjà un surnom, patience.",
                                                    ephemeral=True)
            return
        if not await self._peut(interaction, membre):
            return
        nouveau = random.choice(SURNOMS)
        # enregistré AVANT de renommer : même un redémarrage juste après rendra le pseudo
        en_cours[str(membre.id)] = {"ancien": membre.nick, "fin": time.time() + DUREE_SURNOM}
        await asave_json(GUILD_SETTINGS_FILE, settings)
        try:
            await membre.edit(nick=nouveau, reason=f"/surnom par {interaction.user}")
        except discord.HTTPException:
            en_cours.pop(str(membre.id), None)
            await asave_json(GUILD_SETTINGS_FILE, settings)
            await interaction.response.send_message("❌ Impossible de le renommer.", ephemeral=True)
            return
        await interaction.response.send_message(
            f"🏷️ {membre.mention} s'appelle désormais **{nouveau}**. Retour à la normale dans 10 minutes.")

    @tasks.loop(seconds=30)
    async def restaurer_surnoms(self):
        settings = await aload_json(GUILD_SETTINGS_FILE, {})
        change = False
        for gid, reglages in settings.items():
            en_cours = reglages.get("farces_surnoms") or {}
            guild = self.bot.get_guild(int(gid))
            for mid, info in list(en_cours.items()):
                if time.time() < info["fin"]:
                    continue
                membre = guild.get_member(int(mid)) if guild else None
                if membre is not None:
                    try:
                        await membre.edit(nick=info["ancien"], reason="Fin du /surnom")
                    except discord.HTTPException:
                        pass
                en_cours.pop(mid, None)
                change = True
        if change:
            await asave_json(GUILD_SETTINGS_FILE, settings)

    @restaurer_surnoms.before_loop
    async def _avant_restauration(self):
        await self.bot.wait_until_ready()

    # ── vocal ────────────────────────────────────────────────────────────────

    async def _jouer_en_vocal(self, interaction: discord.Interaction, chemin: str, libelle: str):
        guild = interaction.guild
        voix = interaction.user.voice
        if voix is None or voix.channel is None:
            await interaction.response.send_message("🔈 Rejoins un salon vocal d'abord.", ephemeral=True)
            return
        musique = self.bot.get_cog("Music")
        if musique is not None and musique.players.get(guild.id):
            await interaction.response.send_message("🎵 Saphir Radio tourne, je ne coupe pas la musique.",
                                                    ephemeral=True)
            return
        client = guild.voice_client
        if client is not None and client.is_playing():
            await interaction.response.send_message("🔊 Je suis déjà en train de faire du bruit.", ephemeral=True)
            return
        droits = voix.channel.permissions_for(guild.me)
        if not (droits.connect and droits.speak):
            await interaction.response.send_message(f"❌ Je n'ai pas le droit de parler dans {voix.channel.mention}.",
                                                    ephemeral=True)
            return
        if chemin is None:
            await interaction.response.send_message("❌ Son introuvable sur le serveur.", ephemeral=True)
            return
        if not await self._peut(interaction, vocal=True):
            return
        # réponse AVANT de se connecter : Discord coupe l'interaction au bout de 3 s
        await interaction.response.send_message(f"{libelle} dans {voix.channel.mention}…")
        try:
            if client is None or not client.is_connected():
                client = await voix.channel.connect(self_deaf=True)
            elif client.channel != voix.channel:
                await client.move_to(voix.channel)
            fini = asyncio.Event()
            boucle = asyncio.get_running_loop()
            client.play(discord.FFmpegOpusAudio(chemin, options="-vn"),
                        after=lambda e: boucle.call_soon_threadsafe(fini.set))
            await asyncio.wait_for(fini.wait(), timeout=20)
        except Exception as e:
            print(f"[farces] son non joué : {e}")
        finally:
            # on repart, sauf si quelqu'un a lancé de la musique pendant le son
            vc = guild.voice_client
            if vc is not None and not (musique is not None and musique.players.get(guild.id)):
                try:
                    await asyncio.wait_for(vc.disconnect(force=True), timeout=10)
                except Exception:
                    pass

    @app_commands.command(name="bruitage", description="Saphir débarque dans ton vocal et joue un bruitage")
    @app_commands.describe(son="Le bruitage")
    @app_commands.choices(son=[app_commands.Choice(name=v, value=k) for k, v in BRUITAGES.items()])
    async def bruitage(self, interaction: discord.Interaction, son: app_commands.Choice[str]):
        chemin = os.path.join(FARCES_DIR, "bruitages", f"{son.value}.ogg")
        await self._jouer_en_vocal(interaction, chemin if os.path.exists(chemin) else None, son.name)

    @app_commands.command(name="prout", description="Le grand classique, dans ton salon vocal")
    async def prout(self, interaction: discord.Interaction):
        chemin = os.path.join(FARCES_DIR, "bruitages", "pet.ogg")
        await self._jouer_en_vocal(interaction, chemin if os.path.exists(chemin) else None, "💨 Prout")

    @app_commands.command(name="annonce-vocale", description="Une annonce absurde de Saphir Radio dans ton vocal")
    async def annonce_vocale(self, interaction: discord.Interaction):
        await self._jouer_en_vocal(interaction, fichier_au_hasard("annonces"), "📢 Annonce spéciale")

    @app_commands.command(name="kidnapping", description="Embarque un membre dans un autre vocal pendant 15 s")
    @app_commands.describe(membre="La victime")
    @app_commands.default_permissions(move_members=True)
    async def kidnapping(self, interaction: discord.Interaction, membre: discord.Member):
        if not interaction.user.guild_permissions.move_members:
            await interaction.response.send_message("❌ Réservé à ceux qui peuvent déplacer des membres.",
                                                    ephemeral=True)
            return
        depart = membre.voice.channel if membre.voice else None
        if depart is None:
            await interaction.response.send_message(f"🔈 {membre.display_name} n'est dans aucun vocal.",
                                                    ephemeral=True)
            return
        guild = interaction.guild
        planques = [c for c in guild.voice_channels
                    if c != depart and c != guild.afk_channel
                    and c.permissions_for(guild.me).move_members and c.permissions_for(membre).connect]
        if not planques:
            await interaction.response.send_message("❌ Aucun autre vocal où l'emmener.", ephemeral=True)
            return
        if not await self._peut(interaction, membre, vocal=True):
            return
        planque = random.choice(planques)
        try:
            await membre.move_to(planque, reason=f"/kidnapping par {interaction.user}")
        except discord.HTTPException:
            await interaction.response.send_message("❌ Impossible de le déplacer.", ephemeral=True)
            return
        await interaction.response.send_message(
            f"🚐 {membre.mention} a été **kidnappé** et emmené dans {planque.mention} ! "
            f"Libération dans {DUREE_KIDNAPPING} secondes… normalement.")
        await asyncio.sleep(DUREE_KIDNAPPING)
        # on ne le ramène que s'il est toujours là où on l'a laissé
        if membre.voice is not None and membre.voice.channel == planque and guild.get_channel(depart.id):
            try:
                await membre.move_to(depart, reason="Fin du /kidnapping")
                await interaction.edit_original_response(
                    content=f"🕊️ {membre.mention} a été libéré et ramené dans {depart.mention}. Plus de peur que de mal.")
            except discord.HTTPException:
                pass

    async def cog_app_command_error(self, interaction: discord.Interaction, error: app_commands.AppCommandError):
        await handle_app_error(interaction, error, command_label="une farce")


async def setup(bot):
    await bot.add_cog(Farces(bot))
