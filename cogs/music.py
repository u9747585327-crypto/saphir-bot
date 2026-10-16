"""
cogs/music.py
Lecture de musique dans un salon vocal, à partir d'un lien (YouTube, playlist…) ou
d'une simple recherche texte.

Fonctionnement : yt-dlp résout le lien en flux audio, ffmpeg le décode, discord.py
l'envoie dans le vocal. Un lecteur indépendant par serveur, avec sa file d'attente.

Deux choix d'implémentation qui méritent une explication :

- **L'URL du flux est résolue au dernier moment**, juste avant de jouer le morceau, et
  pas au moment où on l'ajoute à la file. Les URLs de flux YouTube expirent au bout de
  quelques heures : les résoudre à l'avance casserait les longues files d'attente.
- **Les playlists sont lues à plat** (`extract_flat`) : on récupère juste les titres et
  les identifiants, sans interroger YouTube pour chaque morceau. Ajouter une playlist de
  100 titres prend une seconde au lieu d'une minute.
"""

import asyncio
import random
import time
from urllib.parse import parse_qs, urlparse

import discord
from discord import app_commands
from discord.ext import commands

from cogs._shared import handle_app_error
from config import COLORS

try:
    import yt_dlp
except ImportError:  # dépendance absente : le cog se charge mais prévient proprement
    yt_dlp = None


# Options de recherche/extraction. source_address force l'IPv4 : beaucoup d'hébergeurs
# ont une IPv6 que YouTube bloque, ce qui donne des erreurs incompréhensibles.
YTDL_SEARCH = {
    "format": "bestaudio/best",
    "quiet": True,
    "no_warnings": True,
    "default_search": "ytsearch",
    "extract_flat": "in_playlist",
    "skip_download": True,
    "source_address": "0.0.0.0",
}

YTDL_STREAM = {
    "format": "bestaudio/best",
    "quiet": True,
    "no_warnings": True,
    "noplaylist": True,
    "skip_download": True,
    "source_address": "0.0.0.0",
}

# -reconnect : si le flux coupe (réseau, CDN), ffmpeg reprend au lieu de s'arrêter net.
FFMPEG_BEFORE = "-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5"
FFMPEG_OPTIONS = "-vn"

IDLE_TIMEOUT = 300          # 5 min sans rien jouer : le bot quitte le vocal
MAX_QUEUE = 500
QUEUE_PAGE = 10


def format_duration(seconds) -> str:
    """123 -> 2:03, 3700 -> 1:01:40, None -> 'live'."""
    if not seconds:
        return "live"
    seconds = int(seconds)
    heures, reste = divmod(seconds, 3600)
    minutes, secondes = divmod(reste, 60)
    if heures:
        return f"{heures}:{minutes:02d}:{secondes:02d}"
    return f"{minutes}:{secondes:02d}"


class Track:
    """Un morceau en file d'attente. `url` est la page YouTube, pas le flux audio :
    le flux n'est résolu qu'au moment de jouer."""

    __slots__ = ("url", "title", "duration", "requester_id", "thumbnail")

    def __init__(self, url, title, duration=None, requester_id=None, thumbnail=None):
        self.url = url
        self.title = title
        self.duration = duration
        self.requester_id = requester_id
        self.thumbnail = thumbnail


def _extract(query, options):
    """Appel bloquant de yt-dlp, à lancer dans un thread."""
    with yt_dlp.YoutubeDL(options) as ydl:
        return ydl.extract_info(query, download=False)


def lien_de_playlist(query) -> bool:
    """Vrai uniquement pour un lien de playlist *pure* (youtube.com/playlist?list=…).

    Un lien de vidéo copié depuis YouTube pendant qu'une playlist ou un mix tourne
    contient lui aussi `&list=…`, alors que l'utilisateur ne demande que cette vidéo.
    C'est le piège classique : sans cette distinction, un simple lien ajoute des
    centaines de morceaux à la file.
    """
    if not isinstance(query, str) or not query.startswith("http"):
        return False
    url = urlparse(query)
    params = parse_qs(url.query)
    if "v" in params:                       # une vidéo : le `list` n'est qu'un contexte
        return False
    return url.path.rstrip("/").endswith("/playlist") and "list" in params


async def search(query, requester_id, toute_la_playlist=False):
    """Transforme un lien ou une recherche en liste de Track.

    Par défaut, un lien de vidéo ne donne qu'un seul morceau, même s'il traîne un
    `&list=` derrière lui. Les playlists ne sont développées que si l'utilisateur l'a
    explicitement demandé, ou si le lien est un lien de playlist pur.
    """
    options = dict(YTDL_SEARCH)
    options["noplaylist"] = not (toute_la_playlist or lien_de_playlist(query))

    info = await asyncio.to_thread(_extract, query, options)

    if info is None:
        return []

    entries = info.get("entries")
    if entries is None:
        entries = [info]

    tracks = []
    for entry in entries:
        if not entry:
            continue
        url = entry.get("url") or entry.get("webpage_url")
        if not url:
            continue
        # en mode extract_flat, les entrées de playlist ne donnent qu'un identifiant
        if not url.startswith("http"):
            url = f"https://www.youtube.com/watch?v={url}"
        tracks.append(
            Track(
                url=url,
                title=entry.get("title") or "Titre inconnu",
                duration=entry.get("duration"),
                requester_id=requester_id,
                thumbnail=entry.get("thumbnail"),
            )
        )
    return tracks


async def resolve_stream(track):
    """Renvoie l'URL du flux audio pour ce morceau, résolue à l'instant."""
    info = await asyncio.to_thread(_extract, track.url, YTDL_STREAM)
    if info is None:
        raise RuntimeError("yt-dlp n'a rien renvoyé pour ce lien")
    if "entries" in info and info["entries"]:
        info = info["entries"][0]
    if not track.thumbnail:
        track.thumbnail = info.get("thumbnail")
    if not track.duration:
        track.duration = info.get("duration")
    url = info.get("url")
    if not url:
        raise RuntimeError("aucun flux audio trouvé pour ce lien")
    return url


class Player:
    """Le lecteur d'un serveur : sa file, son salon vocal, sa boucle de lecture."""

    def __init__(self, cog, guild, text_channel):
        self.cog = cog
        self.bot = cog.bot
        self.guild = guild
        self.text_channel = text_channel

        self.queue = []
        self.current = None
        self.source = None
        self.started_at = 0.0
        self.volume = 0.5
        self.loop_mode = "off"          # off | track | queue

        self._added = asyncio.Event()   # réveille la boucle quand on ajoute un morceau
        self._finished = asyncio.Event()  # posé par ffmpeg quand le morceau se termine
        self._stopped = False
        self.task = self.bot.loop.create_task(self.runner())

    # ── file d'attente ───────────────────────────────────────────────────────

    def add(self, tracks, en_tete=False):
        libre = MAX_QUEUE - len(self.queue)
        ajoutes = tracks[:max(0, libre)]
        if en_tete:
            self.queue[:0] = ajoutes
        else:
            self.queue.extend(ajoutes)
        self._added.set()
        return len(ajoutes), len(tracks) - len(ajoutes)

    @property
    def voice(self):
        return self.guild.voice_client

    # ── boucle de lecture ────────────────────────────────────────────────────

    async def runner(self):
        try:
            while not self._stopped:
                if not self.queue:
                    self._added.clear()
                    try:
                        await asyncio.wait_for(self._added.wait(), timeout=IDLE_TIMEOUT)
                    except asyncio.TimeoutError:
                        await self.annonce("💤 Personne n'a rien demandé depuis 5 minutes, je quitte le vocal.")
                        await self.cleanup()
                        return
                    continue

                track = self.queue.pop(0)
                self.current = track

                if self.voice is None or not self.voice.is_connected():
                    await self.cleanup()
                    return

                try:
                    stream = await resolve_stream(track)
                except Exception as e:
                    await self.annonce(f"⚠️ Impossible de lire **{track.title}** ({e}) — je passe au suivant.")
                    self.current = None
                    continue

                # PCM + PCMVolumeTransformer : un peu plus coûteux en CPU que l'Opus
                # direct, mais c'est ce qui permet de changer le volume en direct.
                audio = discord.FFmpegPCMAudio(stream, before_options=FFMPEG_BEFORE, options=FFMPEG_OPTIONS)
                self.source = discord.PCMVolumeTransformer(audio, volume=self.volume)

                self._finished.clear()
                self.voice.play(self.source, after=self._apres_lecture)
                self.started_at = time.time()
                await self.annonce(embed=self.embed_lecture(track))

                await self._finished.wait()
                self.source = None

                if self._stopped:
                    return
                if self.loop_mode == "track":
                    self.queue.insert(0, track)
                elif self.loop_mode == "queue":
                    self.queue.append(track)
                self.current = None
        except asyncio.CancelledError:
            raise
        except Exception as e:
            print(f"⚠️ Erreur dans le lecteur musique de {self.guild.name} : {e}")
            await self.cleanup()

    def _apres_lecture(self, error):
        """Appelé par discord.py depuis un autre thread : on repasse proprement sur
        la boucle d'événements avant de toucher à quoi que ce soit."""
        if error:
            print(f"⚠️ Lecture interrompue sur {self.guild.name} : {error}")
        self.bot.loop.call_soon_threadsafe(self._finished.set)

    # ── affichage ────────────────────────────────────────────────────────────

    def embed_lecture(self, track):
        embed = discord.Embed(
            title="🎵 Lecture en cours",
            description=f"**[{track.title}]({track.url})**",
            color=discord.Color(COLORS["saphir"]),
        )
        embed.add_field(name="Durée", value=format_duration(track.duration))
        if track.requester_id:
            embed.add_field(name="Demandé par", value=f"<@{track.requester_id}>")
        if self.queue:
            embed.add_field(name="Dans la file", value=f"{len(self.queue)} morceau(x)")
        if track.thumbnail:
            embed.set_thumbnail(url=track.thumbnail)
        return embed

    async def annonce(self, contenu=None, embed=None):
        if self.text_channel is None:
            return
        try:
            await self.text_channel.send(content=contenu, embed=embed)
        except discord.HTTPException:
            pass

    # ── arrêt ────────────────────────────────────────────────────────────────

    async def cleanup(self):
        self._stopped = True
        self.queue.clear()
        self.current = None
        voice = self.voice
        if voice is not None:
            try:
                voice.stop()
                # force=True suffit normalement, mais une passerelle vocale qui ne
                # répond plus peut faire traîner l'appel : on ne bloque jamais dessus.
                await asyncio.wait_for(voice.disconnect(force=True), timeout=10)
            except Exception:
                pass
        self.cog.players.pop(self.guild.id, None)
        if self.task and not self.task.done():
            self.task.cancel()


class Music(commands.Cog):
    """Commandes de musique : /play, /skip, /queue…"""

    def __init__(self, bot):
        self.bot = bot
        self.players = {}

    def player_de(self, interaction):
        return self.players.get(interaction.guild.id)

    async def cog_unload(self):
        for player in list(self.players.values()):
            await player.cleanup()

    # ── helpers ──────────────────────────────────────────────────────────────

    async def rejoindre(self, interaction):
        """Connecte le bot au salon de l'utilisateur, ou renvoie None avec un message
        d'erreur déjà envoyé."""
        voix = interaction.user.voice
        if voix is None or voix.channel is None:
            await interaction.followup.send("❌ Tu dois être dans un salon vocal.", ephemeral=True)
            return None

        salon = voix.channel
        permissions = salon.permissions_for(interaction.guild.me)
        if not permissions.connect or not permissions.speak:
            await interaction.followup.send(
                f"❌ Je n'ai pas le droit de rejoindre ou de parler dans **{salon.name}**.", ephemeral=True
            )
            return None

        client = interaction.guild.voice_client
        if client is None:
            try:
                client = await salon.connect(self_deaf=True)
            except discord.ClientException:
                client = interaction.guild.voice_client
            except Exception as e:
                await interaction.followup.send(f"❌ Connexion au vocal impossible : {e}", ephemeral=True)
                return None
        elif client.channel != salon:
            await client.move_to(salon)

        player = self.players.get(interaction.guild.id)
        if player is None:
            player = Player(self, interaction.guild, interaction.channel)
            self.players[interaction.guild.id] = player
        else:
            player.text_channel = interaction.channel
        return player

    async def exige_player(self, interaction):
        player = self.player_de(interaction)
        if player is None or player.voice is None:
            await interaction.response.send_message("❌ Je ne joue rien pour le moment.", ephemeral=True)
            return None
        return player

    # ── commandes ────────────────────────────────────────────────────────────

    @app_commands.command(name="play", description="Joue un lien (YouTube…) ou lance une recherche")
    @app_commands.describe(
        recherche="Un lien, ou simplement un titre à chercher",
        playlist="Ajouter toute la playlist du lien, et pas seulement la vidéo",
    )
    async def play(self, interaction: discord.Interaction, recherche: str, playlist: bool = False):
        await self.ajouter(interaction, recherche, en_tete=False, toute_la_playlist=playlist)

    @app_commands.command(name="playnext", description="Ajoute en tête de file, juste après le morceau en cours")
    @app_commands.describe(
        recherche="Un lien, ou simplement un titre à chercher",
        playlist="Ajouter toute la playlist du lien, et pas seulement la vidéo",
    )
    async def playnext(self, interaction: discord.Interaction, recherche: str, playlist: bool = False):
        await self.ajouter(interaction, recherche, en_tete=True, toute_la_playlist=playlist)

    async def ajouter(self, interaction: discord.Interaction, recherche: str, en_tete: bool,
                      toute_la_playlist: bool = False):
        if yt_dlp is None:
            await interaction.response.send_message(
                "❌ yt-dlp n'est pas installé sur le serveur, la musique est indisponible.", ephemeral=True
            )
            return

        await interaction.response.defer(thinking=True)
        player = await self.rejoindre(interaction)
        if player is None:
            return

        try:
            tracks = await search(recherche, interaction.user.id, toute_la_playlist=toute_la_playlist)
        except Exception as e:
            await interaction.followup.send(f"❌ Recherche impossible : {e}", ephemeral=True)
            return

        if not tracks:
            await interaction.followup.send("❌ Aucun résultat pour cette recherche.", ephemeral=True)
            return

        ajoutes, refuses = player.add(tracks, en_tete=en_tete)
        if ajoutes == 0:
            await interaction.followup.send(f"❌ La file est pleine ({MAX_QUEUE} morceaux).", ephemeral=True)
            return

        place = "en tête de file" if en_tete else "à la file"
        if ajoutes == 1:
            track = tracks[0]
            message = f"✅ Ajouté {place} : **{track.title}** ({format_duration(track.duration)})"
        else:
            # On dit explicitement qu'une playlist a été développée : sans ça, voir
            # arriver 500 morceaux après un seul /play reste une énigme.
            raison = "playlist demandée" if toute_la_playlist else "lien de playlist"
            message = f"✅ **{ajoutes} morceaux** ajoutés {place} ({raison})."
        if refuses:
            message += f"\n⚠️ {refuses} morceau(x) ignoré(s), la file est pleine."
        await interaction.followup.send(message)

    @app_commands.command(name="skip", description="Passe au morceau suivant")
    async def skip(self, interaction: discord.Interaction):
        player = await self.exige_player(interaction)
        if player is None:
            return
        if not player.voice.is_playing() and not player.voice.is_paused():
            await interaction.response.send_message("❌ Rien à passer.", ephemeral=True)
            return
        titre = player.current.title if player.current else "le morceau"
        player.voice.stop()  # déclenche la suite de la boucle via after=
        await interaction.response.send_message(f"⏭️ **{titre}** passé.")

    @app_commands.command(name="stop", description="Arrête tout, vide la file et quitte le vocal")
    async def stop(self, interaction: discord.Interaction):
        player = await self.exige_player(interaction)
        if player is None:
            return
        # On répond AVANT de nettoyer : Discord ferme l'interaction au bout de 3 s, et
        # une déconnexion du vocal peut prendre plus longtemps que ça.
        await interaction.response.send_message("⏹️ File vidée, je quitte le vocal.")
        await player.cleanup()

    @app_commands.command(name="pause", description="Met la lecture en pause")
    async def pause(self, interaction: discord.Interaction):
        player = await self.exige_player(interaction)
        if player is None:
            return
        if not player.voice.is_playing():
            await interaction.response.send_message("❌ Rien n'est en cours de lecture.", ephemeral=True)
            return
        player.voice.pause()
        await interaction.response.send_message("⏸️ En pause. `/resume` pour reprendre.")

    @app_commands.command(name="resume", description="Reprend la lecture")
    async def resume(self, interaction: discord.Interaction):
        player = await self.exige_player(interaction)
        if player is None:
            return
        if not player.voice.is_paused():
            await interaction.response.send_message("❌ Ce n'est pas en pause.", ephemeral=True)
            return
        player.voice.resume()
        await interaction.response.send_message("▶️ C'est reparti.")

    @app_commands.command(name="queue", description="Affiche la file d'attente")
    async def queue(self, interaction: discord.Interaction):
        player = self.player_de(interaction)
        if player is None or (not player.queue and player.current is None):
            await interaction.response.send_message("La file est vide.", ephemeral=True)
            return

        lignes = []
        if player.current:
            ecoule = format_duration(time.time() - player.started_at)
            lignes.append(
                f"**En cours** · [{player.current.title}]({player.current.url}) "
                f"`{ecoule} / {format_duration(player.current.duration)}`"
            )
            lignes.append("")

        for i, track in enumerate(player.queue[:QUEUE_PAGE], start=1):
            lignes.append(f"`{i}.` [{track.title}]({track.url}) `{format_duration(track.duration)}`")

        reste = len(player.queue) - QUEUE_PAGE
        if reste > 0:
            lignes.append(f"\n… et {reste} autre(s).")

        total = sum(t.duration or 0 for t in player.queue)
        embed = discord.Embed(
            title="🎶 File d'attente",
            description="\n".join(lignes),
            color=discord.Color(COLORS["saphir"]),
        )
        embed.set_footer(text=f"{len(player.queue)} en attente · {format_duration(total)} au total · boucle : {player.loop_mode}")
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="nowplaying", description="Affiche le morceau en cours")
    async def nowplaying(self, interaction: discord.Interaction):
        player = self.player_de(interaction)
        if player is None or player.current is None:
            await interaction.response.send_message("❌ Je ne joue rien pour le moment.", ephemeral=True)
            return
        embed = player.embed_lecture(player.current)
        embed.add_field(
            name="Avancement",
            value=f"`{format_duration(time.time() - player.started_at)} / {format_duration(player.current.duration)}`",
            inline=False,
        )
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="loop", description="Répète le morceau en cours, toute la file, ou rien")
    @app_commands.describe(mode="Ce qu'il faut répéter")
    @app_commands.choices(mode=[
        app_commands.Choice(name="Désactivé", value="off"),
        app_commands.Choice(name="Le morceau en cours", value="track"),
        app_commands.Choice(name="Toute la file", value="queue"),
    ])
    async def loop(self, interaction: discord.Interaction, mode: app_commands.Choice[str]):
        player = await self.exige_player(interaction)
        if player is None:
            return
        player.loop_mode = mode.value
        libelle = {"off": "🔁 Répétition désactivée.", "track": "🔂 Je répète le morceau en cours.",
                   "queue": "🔁 Je répète toute la file."}[mode.value]
        await interaction.response.send_message(libelle)

    @app_commands.command(name="shuffle", description="Mélange la file d'attente")
    async def shuffle(self, interaction: discord.Interaction):
        player = await self.exige_player(interaction)
        if player is None:
            return
        if len(player.queue) < 2:
            await interaction.response.send_message("❌ Pas assez de morceaux en file pour mélanger.", ephemeral=True)
            return
        random.shuffle(player.queue)
        await interaction.response.send_message(f"🔀 {len(player.queue)} morceaux mélangés.")

    @app_commands.command(name="volume", description="Règle le volume, de 0 à 200 %")
    @app_commands.describe(niveau="0 = muet, 100 = normal, 200 = double")
    async def volume(self, interaction: discord.Interaction, niveau: app_commands.Range[int, 0, 200]):
        player = await self.exige_player(interaction)
        if player is None:
            return
        player.volume = niveau / 100
        if player.source is not None:
            player.source.volume = player.volume
        await interaction.response.send_message(f"🔊 Volume réglé sur {niveau} %.")

    @app_commands.command(name="clear", description="Vide la file d'attente sans couper le morceau en cours")
    async def clear(self, interaction: discord.Interaction):
        player = await self.exige_player(interaction)
        if player is None:
            return
        nombre = len(player.queue)
        if nombre == 0:
            await interaction.response.send_message("La file est déjà vide.", ephemeral=True)
            return
        player.queue.clear()
        await interaction.response.send_message(
            f"🗑️ {nombre} morceau(x) retiré(s). Le morceau en cours continue — `/skip` pour l'arrêter aussi."
        )

    @app_commands.command(name="remove", description="Retire un morceau de la file, par son numéro")
    @app_commands.describe(numero="Le numéro affiché par /queue")
    async def remove(self, interaction: discord.Interaction, numero: app_commands.Range[int, 1, MAX_QUEUE]):
        player = await self.exige_player(interaction)
        if player is None:
            return
        if numero > len(player.queue):
            await interaction.response.send_message(f"❌ Il n'y a que {len(player.queue)} morceau(x) en file.", ephemeral=True)
            return
        track = player.queue.pop(numero - 1)
        await interaction.response.send_message(f"🗑️ **{track.title}** retiré de la file.")

    # ── le bot quitte quand il reste seul ────────────────────────────────────

    @commands.Cog.listener()
    async def on_voice_state_update(self, member, before, after):
        if member.bot:
            return
        player = self.players.get(member.guild.id)
        if player is None or player.voice is None:
            return
        salon = player.voice.channel
        if salon is None:
            return
        if not any(not m.bot for m in salon.members):
            await player.annonce("👋 Plus personne dans le vocal, je m'en vais.")
            await player.cleanup()

    # ── erreurs ──────────────────────────────────────────────────────────────

    async def cog_app_command_error(self, interaction: discord.Interaction, error: app_commands.AppCommandError):
        await handle_app_error(interaction, error, command_label="une commande de musique")


async def setup(bot):
    await bot.add_cog(Music(bot))
