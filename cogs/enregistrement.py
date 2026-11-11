"""
cogs/enregistrement.py
/rec : enregistre un salon vocal, une piste par personne, puis poste le mixage en MP3.

Enregistrer des gens à leur insu est illégal (art. 226-1 du Code pénal) : tout ici est
pensé pour que personne ne puisse l'ignorer.
- seuls les admins et le propriétaire lancent un /rec ;
- annonce vocale au début et à la fin, message dans le chat du vocal, statut du salon
  « 🔴 Enregistrement » ;
- chaque personne qui arrive pendant l'enregistrement est prévenue ;
- /rec-sans-moi : n'importe qui retire sa voix (sa piste est effacée, la suite ignorée) ;
- /stop-rec : n'importe quelle personne présente dans le vocal arrête tout (c'est
  le seul moyen : déconnecté ou déplacé, Saphir revient) ; pas de
  durée maximale, l'enregistrement s'arrête aussi quand le vocal se vide.

L'écoute passe par discord-ext-voice-recv, dans une version qui sait déchiffrer le
chiffrement de bout en bout (DAVE) des vocaux Discord : la version publiée sur PyPI ne
le sait pas et produit du bruit. Voir requirements.txt.

Discord n'envoie rien quand quelqu'un se tait : chaque piste est donc complétée par du
silence calé sur l'horloge, sans quoi les voix se décaleraient au mixage.
"""

import asyncio
import datetime
import os
import shutil
import subprocess
import threading
import time

import discord
from discord import app_commands
from discord.ext import commands

from cogs._shared import handle_app_error
from config import GUILD_SETTINGS_FILE
from storage import aload_json, asave_json

try:
    from discord.ext import voice_recv
except ImportError:   # le cog se charge quand même, /rec explique ce qui manque
    voice_recv = None

_BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DOSSIER_REC = os.path.join(_BASE, "data", "enregistrements")
ANNONCES = os.path.join(_BASE, "assets", "enregistrement")

NOM_SALON_LOGS = "「🎙️」enregistrements"
TAUX = 48000                # Discord : 48 kHz, stéréo, 16 bits
OCTETS_PAR_ECHANTILLON = 4
TROU_MIN = 960 * 3          # en dessous de 60 ms de trou, inutile de combler


class Pistes(voice_recv.AudioSink if voice_recv else object):
    """Reçoit l'audio de chaque membre et l'encode au fil de l'eau (un ffmpeg par
    personne, en Opus mono) : rien de gros ne reste en mémoire ni sur le disque.
    Appelé depuis le thread de réception de la bibliothèque, d'où le verrou."""

    def __init__(self, dossier: str):
        super().__init__()
        self.dossier = dossier
        self.debut = time.monotonic()
        self.pistes = {}            # user_id -> {"proc", "ecrits", "decalage", "nom"}
        self.exclus = set()
        self._verrou = threading.Lock()

    def wants_opus(self) -> bool:
        return False

    def _ouvrir(self, user):
        chemin = os.path.join(self.dossier, f"{user.id}.ogg")
        proc = subprocess.Popen(
            ["ffmpeg", "-loglevel", "error", "-f", "s16le", "-ar", str(TAUX), "-ac", "2", "-i", "pipe:0",
             "-ac", "1", "-c:a", "libopus", "-b:a", "48k", "-y", chemin],
            stdin=subprocess.PIPE)
        return {"proc": proc, "ecrits": 0, "decalage": time.monotonic() - self.debut,
                "nom": getattr(user, "display_name", str(user)), "chemin": chemin}

    def write(self, user, data):
        if user is None or getattr(user, "bot", False) or not data.pcm:
            return
        with self._verrou:
            if user.id in self.exclus:
                return
            piste = self.pistes.get(user.id)
            if piste is None:
                piste = self.pistes[user.id] = self._ouvrir(user)
            # silence pendant qu'il se taisait : la piste reste calée sur l'horloge
            attendu = int((time.monotonic() - self.debut - piste["decalage"]) * TAUX)
            trou = attendu - piste["ecrits"]
            try:
                while trou > TROU_MIN:
                    bloc = min(trou, TAUX)
                    piste["proc"].stdin.write(b"\x00" * (bloc * OCTETS_PAR_ECHANTILLON))
                    piste["ecrits"] += bloc
                    trou -= bloc
                piste["proc"].stdin.write(data.pcm)
                piste["ecrits"] += len(data.pcm) // OCTETS_PAR_ECHANTILLON
            except (BrokenPipeError, OSError):
                pass

    def retirer(self, user_id: int):
        """/rec-sans-moi : la piste est fermée et effacée, la suite ignorée."""
        with self._verrou:
            self.exclus.add(user_id)
            piste = self.pistes.pop(user_id, None)
        if piste is not None:
            self._fermer(piste)
            try:
                os.remove(piste["chemin"])
            except OSError:
                pass

    @staticmethod
    def _fermer(piste):
        try:
            piste["proc"].stdin.close()
            piste["proc"].wait(timeout=30)
        except Exception:
            piste["proc"].kill()

    def cleanup(self):
        """Appelé par la bibliothèque à chaque arrêt d'écoute, y compris quand Saphir est
        déconnecté : on ne ferme rien ici, sinon la reconnexion écrirait dans le vide.
        La vraie fermeture, c'est fermer(), à la fin de l'enregistrement."""

    def fermer(self):
        with self._verrou:
            pistes = list(self.pistes.values())
        for p in pistes:
            self._fermer(p)


def decouper(fichier: str, taille_max: int) -> list:
    """Coupe un MP3 trop lourd en parties qui passent sous `taille_max` (marge de 10 %).
    Copie directe du flux (-c copy) : instantané, sans perte de qualité."""
    if os.path.getsize(fichier) <= taille_max:
        return [fichier]
    duree = float(subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", fichier],
        capture_output=True, text=True).stdout or 0)
    if duree <= 0:
        return [fichier]
    nb = int(os.path.getsize(fichier) / (taille_max * 0.9)) + 1
    tranche = duree / nb
    modele = os.path.join(os.path.dirname(fichier), "partie_%02d.mp3")
    subprocess.run(["ffmpeg", "-loglevel", "error", "-i", fichier, "-f", "segment", "-segment_time",
                    f"{tranche:.2f}", "-c", "copy", "-reset_timestamps", "1", "-y", modele])
    dossier = os.path.dirname(fichier)
    return sorted(os.path.join(dossier, f) for f in os.listdir(dossier)
                  if f.startswith("partie_") and f.endswith(".mp3"))


async def envoyer_en_parties(salon, entete, fichier, nom):
    """Poste l'enregistrement, en plusieurs messages si besoin. True si tout est parti."""
    parties = await asyncio.to_thread(decouper, fichier, salon.guild.filesize_limit)
    n = len(parties)
    for i, partie in enumerate(parties, 1):
        if os.path.getsize(partie) > salon.guild.filesize_limit:
            await salon.send(f"{entete}\n📁 Partie {i}/{n} encore trop lourde : gardée sur le serveur, "
                             f"`{os.path.relpath(partie, _BASE)}`.")
            return False
        texte = entete if n == 1 else (f"{entete}\n📼 Partie **{i}/{n}**" if i == 1 else f"📼 Partie **{i}/{n}**")
        suffixe = "" if n == 1 else f"-partie{i}"
        await salon.send(texte, allowed_mentions=discord.AllowedMentions.none(),
                         file=discord.File(partie, filename=f"{nom}{suffixe}.mp3"))
    return True


def mixer(pistes: list, sortie: str) -> bool:
    """Mixe les pistes (chacune décalée à son heure d'arrivée) en un MP3 mono."""
    pistes = [p for p in pistes if os.path.exists(p["chemin"]) and os.path.getsize(p["chemin"]) > 0]
    if not pistes:
        return False
    cmd = ["ffmpeg", "-loglevel", "error"]
    for p in pistes:
        cmd += ["-i", p["chemin"]]
    filtres = [f"[{i}:a]adelay={int(p['decalage'] * 1000)}:all=1[a{i}]" for i, p in enumerate(pistes)]
    entrees = "".join(f"[a{i}]" for i in range(len(pistes)))
    filtres.append(f"{entrees}amix=inputs={len(pistes)}:normalize=0:duration=longest[m]")
    cmd += ["-filter_complex", ";".join(filtres), "-map", "[m]", "-ac", "1", "-b:a", "64k", "-y", sortie]
    return subprocess.run(cmd).returncode == 0 and os.path.exists(sortie)


class Enregistrement(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.sessions = {}          # guild_id -> session (dict)

    # ── outils ───────────────────────────────────────────────────────────────

    async def _annonce_vocale(self, vc, nom):
        chemin = os.path.join(ANNONCES, f"{nom}.ogg")
        if not os.path.exists(chemin) or vc is None or not vc.is_connected():
            return
        if vc.is_playing() or vc.is_paused():
            # musique en cours : l'annonce passe au milieu, puis le morceau reprend
            musique = self.bot.get_cog("Music")
            player = musique.players.get(vc.guild.id) if musique else None
            if player is not None and player.intercaler(chemin):
                await asyncio.sleep(7)
            return
        fini = asyncio.Event()
        boucle = asyncio.get_running_loop()
        try:
            vc.play(discord.FFmpegOpusAudio(chemin, options="-vn"),
                    after=lambda e: boucle.call_soon_threadsafe(fini.set))
            await asyncio.wait_for(fini.wait(), timeout=15)
        except Exception as e:
            print(f"[rec] annonce « {nom} » non jouée : {e}")

    async def _statut(self, salon, texte):
        try:
            await salon.edit(status=texte)
        except (discord.HTTPException, TypeError, AttributeError):
            pass

    async def salon_logs(self, guild):
        """Salon « enregistrements » dans la catégorie des logs : créé au premier besoin,
        avec les droits de la catégorie (staff seulement), retrouvé ensuite par son ID."""
        settings = await aload_json(GUILD_SETTINGS_FILE, {})
        ids = settings.setdefault(str(guild.id), {}).setdefault("log_channel_ids", {})
        salon = guild.get_channel(ids.get("recordings") or 0)
        if salon is not None:
            return salon
        autre = guild.get_channel(ids.get("voice") or ids.get("moderation") or 0)
        categorie = autre.category if autre is not None else discord.utils.find(
            lambda c: "LOGS" in c.name.upper(), guild.categories)
        try:
            salon = await guild.create_text_channel(
                NOM_SALON_LOGS, category=categorie,
                overwrites=categorie.overwrites if categorie else {
                    guild.default_role: discord.PermissionOverwrite(view_channel=False)},
                reason="Salon des enregistrements vocaux (/rec)")
        except discord.HTTPException as e:
            print(f"[rec] salon d'enregistrements non créé : {e}")
            return None
        ids["recordings"] = salon.id
        await asave_json(GUILD_SETTINGS_FILE, settings)
        return salon

    # ── commandes ────────────────────────────────────────────────────────────

    @app_commands.command(name="rec", description="Enregistre ton salon vocal (annoncé à tous)")
    @app_commands.default_permissions(manage_guild=True)
    async def rec(self, interaction: discord.Interaction):
        droits = interaction.user.guild_permissions
        if not (droits.administrator or droits.manage_guild):
            await interaction.response.send_message("🔒 Réservé aux admins et au propriétaire.", ephemeral=True)
            return
        if voice_recv is None:
            await interaction.response.send_message("❌ Le module d'écoute n'est pas installé sur le serveur.",
                                                    ephemeral=True)
            return
        guild = interaction.guild
        voix = interaction.user.voice
        if voix is None or voix.channel is None:
            await interaction.response.send_message("🔈 Rejoins le vocal à enregistrer.", ephemeral=True)
            return
        if guild.id in self.sessions:
            await interaction.response.send_message("🔴 Un enregistrement est déjà en cours.", ephemeral=True)
            return
        salon = voix.channel
        vc = guild.voice_client
        if vc is not None:
            if vc.channel != salon:
                await interaction.response.send_message(
                    f"🎵 Je suis déjà dans {vc.channel.mention}. Rejoins-le, ou `/stop` d'abord.", ephemeral=True)
                return
            if not isinstance(vc, voice_recv.VoiceRecvClient):
                await interaction.response.send_message(
                    "🎵 Cette session de musique a démarré avant la mise à jour : fais `/stop` puis relance.",
                    ephemeral=True)
                return
        await interaction.response.defer(thinking=True)
        try:
            if vc is None:
                # pas de self_deaf : un bot sourd ne reçoit rien
                vc = await salon.connect(cls=voice_recv.VoiceRecvClient, self_deaf=False)
            else:
                await guild.change_voice_state(channel=salon, self_deaf=False)
        except Exception as e:
            await interaction.followup.send(f"❌ Connexion au vocal impossible : {e}")
            return

        dossier = os.path.join(DOSSIER_REC, f"{guild.id}-{int(time.time())}")
        os.makedirs(dossier, exist_ok=True)
        pistes = Pistes(dossier)
        session = {"vc": vc, "salon": salon, "pistes": pistes, "dossier": dossier,
                   "texte": interaction.channel, "lanceur": interaction.user, "debut": time.time()}
        self.sessions[guild.id] = session

        await self._annonce_vocale(vc, "debut")
        vc.listen(pistes)
        await self._statut(salon, "🔴 Enregistrement en cours")
        presents = [m for m in salon.members if not m.bot]
        avis = (f"🔴 **Enregistrement en cours** dans {salon.mention}, lancé par {interaction.user.mention}.\n"
                f"Pour ne pas être enregistré : `/rec-sans-moi`. Pour tout arrêter : `/stop-rec`.\n"
                f"-# Pas de limite de durée · le fichier ira dans les logs du staff.")
        await interaction.followup.send(avis)
        try:
            await salon.send(f"🔴 {' '.join(m.mention for m in presents)} ce vocal est **enregistré**. "
                             "`/rec-sans-moi` pour retirer ta voix.",
                             allowed_mentions=discord.AllowedMentions(users=presents))
        except discord.HTTPException:
            pass

    @app_commands.command(name="stop-rec", description="Arrête l'enregistrement du vocal et poste le fichier")
    async def stop_rec(self, interaction: discord.Interaction):
        session = self.sessions.get(interaction.guild.id)
        if session is None:
            await interaction.response.send_message("Aucun enregistrement en cours.", ephemeral=True)
            return
        voix = interaction.user.voice
        dans_le_salon = voix is not None and voix.channel == session["salon"]
        droits = interaction.user.guild_permissions
        if not (dans_le_salon or droits.administrator or droits.manage_guild):
            await interaction.response.send_message("Il faut être dans le vocal enregistré pour l'arrêter.",
                                                    ephemeral=True)
            return
        await interaction.response.send_message(f"⏹️ Enregistrement arrêté par {interaction.user.mention}, "
                                                "je prépare le fichier…")
        await self.terminer(interaction.guild.id, raison=f"arrêté par {interaction.user.display_name}")

    @app_commands.command(name="rec-sans-moi", description="Retire ta voix de l'enregistrement en cours")
    async def rec_sans_moi(self, interaction: discord.Interaction):
        session = self.sessions.get(interaction.guild.id)
        if session is None:
            await interaction.response.send_message("Aucun enregistrement en cours.", ephemeral=True)
            return
        await asyncio.to_thread(session["pistes"].retirer, interaction.user.id)
        await interaction.response.send_message(
            "✅ Ta voix est retirée : ce qui avait été enregistré est effacé, et la suite ne le sera pas.",
            ephemeral=True)
        try:
            await session["salon"].send(f"🔕 {interaction.user.display_name} a retiré sa voix de l'enregistrement.")
        except discord.HTTPException:
            pass

    # ── fin ──────────────────────────────────────────────────────────────────

    async def terminer(self, guild_id, raison: str):
        session = self.sessions.pop(guild_id, None)
        if session is None:
            return
        vc, salon, pistes = session["vc"], session["salon"], session["pistes"]
        try:
            if vc.is_listening():
                vc.stop_listening()
        except Exception:
            pass
        await asyncio.to_thread(pistes.fermer)
        musique = self.bot.get_cog("Music")
        en_musique = musique is not None and musique.players.get(guild_id) is not None
        if vc.is_connected():
            await self._annonce_vocale(vc, "fin")
            if not en_musique:          # la musique continue si elle tournait
                try:
                    await asyncio.wait_for(vc.disconnect(force=True), timeout=10)
                except Exception:
                    pass
        await self._statut(salon, None)

        duree = int(time.time() - session["debut"])
        sortie = os.path.join(session["dossier"], "enregistrement.mp3")
        ok = await asyncio.to_thread(mixer, list(pistes.pistes.values()), sortie)
        logs = await self.salon_logs(salon.guild)
        texte = logs or session["texte"]       # repli : le salon où /rec a été lancé
        if logs is not None:
            try:
                await session["texte"].send(f"🎙️ Enregistrement de **{salon.name}** terminé ({raison}), "
                                            "envoyé dans les logs du staff.")
            except discord.HTTPException:
                pass
        voix = ", ".join(p["nom"] for p in pistes.pistes.values()) or "personne"
        entete = (f"🎙️ **Enregistrement de {salon.name}** ({duree // 60} min {duree % 60:02d} s, {raison})\n"
                  f"Lancé par {session['lanceur'].mention} · voix : {voix}")
        try:
            if not ok:
                await texte.send(f"{entete}\n⚠️ Rien d'audible n'a été capté.")
            elif not await envoyer_en_parties(texte, entete, sortie, f"rec-{salon.name[:40]}"):
                return          # une partie n'a pas pu partir : on garde tout sur le serveur
        except discord.HTTPException as e:
            print(f"[rec] envoi du fichier impossible : {e}")
            return
        shutil.rmtree(session["dossier"], ignore_errors=True)

    @commands.Cog.listener()
    async def on_ready(self):
        for guild in self.bot.guilds:
            salon = await self.salon_logs(guild)
            if salon is not None:
                await self._rattrapage(guild, salon)

    async def _rattrapage(self, guild, salon):
        """Enregistrements restés sur le serveur (trop lourds avant le découpage, envoi
        raté) : postés au démarrage, puis effacés."""
        try:
            dossiers = sorted(d for d in os.listdir(DOSSIER_REC) if d.startswith(f"{guild.id}-"))
        except FileNotFoundError:
            return
        for d in dossiers:
            chemin = os.path.join(DOSSIER_REC, d)
            mp3 = os.path.join(chemin, "enregistrement.mp3")
            if any(s["dossier"] == chemin for s in self.sessions.values()) or not os.path.exists(mp3):
                continue
            quand = discord.utils.format_dt(datetime.datetime.fromtimestamp(int(d.split("-")[1])), "f")
            try:
                if await envoyer_en_parties(salon, f"🎙️ **Enregistrement en attente** (lancé le {quand})", mp3, f"rec-{d}"):
                    shutil.rmtree(chemin, ignore_errors=True)
            except discord.HTTPException as e:
                print(f"[rec] rattrapage de {d} impossible : {e}")

    # ── surveillance du vocal ────────────────────────────────────────────────

    @commands.Cog.listener()
    async def on_voice_state_update(self, member, before, after):
        session = self.sessions.get(member.guild.id)
        if session is None:
            return
        salon = session["salon"]
        if member.id == self.bot.user.id:
            await self._garder_en_place(member.guild, session, after)
            return
        if member.bot:
            return
        if after.channel == salon and before.channel != salon:
            try:
                await salon.send(f"🔴 {member.mention}, ce vocal est **enregistré**. "
                                 "`/rec-sans-moi` pour retirer ta voix.",
                                 allowed_mentions=discord.AllowedMentions(users=[member]))
            except discord.HTTPException:
                pass
        if before.channel == salon and not any(not m.bot for m in salon.members):
            await self.terminer(member.guild.id, raison="plus personne dans le vocal")

    async def _garder_en_place(self, guild, session, after):
        """Pendant un /rec, Saphir ne se laisse ni déconnecter, ni déplacer, ni rendre
        sourd : il revient et l'enregistrement continue (les pistes comblent le trou).
        Seul /stop-rec l'arrête. Après 5 échecs de suite (salon supprimé…), on termine
        proprement avec ce qui a été enregistré."""
        salon = session["salon"]
        try:
            if after.channel is None:
                await asyncio.sleep(1)
                if guild.id not in self.sessions or guild.voice_client is not None:
                    return
                if guild.get_channel(salon.id) is None:
                    await self.terminer(guild.id, raison="le salon vocal a été supprimé")
                    return
                vc = await salon.connect(cls=voice_recv.VoiceRecvClient, self_deaf=False)
                session["vc"] = vc
                vc.listen(session["pistes"])
                session["retours"] = 0
                try:
                    await salon.send("🔴 On m'a déconnecté : je suis revenu, l'enregistrement continue. "
                                     "`/stop-rec` pour l'arrêter.")
                except discord.HTTPException:
                    pass
            elif after.channel != salon:
                await guild.voice_client.move_to(salon)
            elif after.deaf or after.self_deaf:
                await guild.me.edit(deafen=False)
                await guild.change_voice_state(channel=salon, self_deaf=False)
        except Exception as e:
            session["retours"] = session.get("retours", 0) + 1
            print(f"[rec] retour dans le vocal impossible ({session['retours']}/5) : {e}")
            if session["retours"] >= 5:
                await self.terminer(guild.id, raison="Saphir n'a pas pu revenir dans le vocal")

    async def cog_unload(self):
        for gid in list(self.sessions):
            await self.terminer(gid, raison="redémarrage de Saphir")

    async def cog_app_command_error(self, interaction, error):
        await handle_app_error(interaction, error, command_label="l'enregistrement")


async def setup(bot):
    await bot.add_cog(Enregistrement(bot))
