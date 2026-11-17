"""
cogs/casiers.py
Un casier par membre, pour le staff : un forum « casiers » dans les logs, un fil par
membre.

- le premier message du fil est la fiche : photo, pseudo, ID, création du compte, arrivée
  sur le serveur, rôles, anciens pseudos, temps passé en vocal, invitation utilisée ;
- ensuite, tout ce que les logs enregistrent sur ce membre y est recopié au fil de l'eau,
  à l'heure près : arrivées et départs, invitation utilisée, sanctions, rôles, pseudos,
  vocal (connexions, changements, durée, micro, caméra…), messages supprimés ou modifiés
  avec leurs images. Les logs d'origine restent en place ; le casier est une copie.
- un membre qui quitte le serveur garde son casier, qui reprend s'il revient.

Seules des informations que Discord donne au serveur sont utilisées. Le forum reprend
les droits des autres salons de logs : invisible pour les membres.

Les casiers manquants sont créés au démarrage, un toutes les quelques secondes pour ne
pas se faire freiner par Discord. /fiche @membre met une fiche à jour et donne son lien.
"""

import asyncio
import datetime
import re

import discord
from discord import app_commands
from discord.ext import commands

from config import COLORS, GUILD_SETTINGS_FILE
from services import vocal_store
from storage import aload_json, asave_json

NOM_FORUM = "「🗂️」casiers"
HISTO_PSEUDOS = "data/historique_pseudos.json"
DELAI_CREATION = 3          # s entre deux créations de casier au démarrage


_MOTIFS_ID = (r"Cible ID : (\d{17,20})", r"^ID : (\d{17,20})", r"ID auteur : (\d{17,20})", r"ID membre : (\d{17,20})")


def membre_concerne(embed) -> int | None:
    """L'ID du membre dont parle un log, lu dans son pied de page."""
    pied = embed.footer.text if embed.footer and embed.footer.text else ""
    for motif in _MOTIFS_ID:
        m = re.search(motif, pied)
        if m:
            return int(m.group(1))
    return None


def _date(dt):
    return f"{discord.utils.format_dt(dt, 'D')} ({discord.utils.format_dt(dt, 'R')})" if dt else "inconnue"


class Casiers(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self._verrou = asyncio.Lock()
        self._remplissage = None

    # ── réglages ─────────────────────────────────────────────────────────────

    async def _ids(self, guild):
        settings = await aload_json(GUILD_SETTINGS_FILE, {})
        return settings, settings.setdefault(str(guild.id), {}).setdefault("casiers", {})

    async def forum(self, guild):
        settings = await aload_json(GUILD_SETTINGS_FILE, {})
        reglages = settings.setdefault(str(guild.id), {})
        forum = guild.get_channel(reglages.get("casiers_forum_id") or 0)
        if isinstance(forum, discord.ForumChannel):
            return forum
        logs = self.bot.get_cog("Logs")
        modele = await logs._channel_for(guild, "voice") if logs else None
        if modele is None:
            print(f"[casiers] {guild.name} : pas de salon de logs, forum non créé")
            return None
        try:
            forum = await guild.create_forum(NOM_FORUM, category=modele.category, overwrites=modele.overwrites,
                                             topic="Un fil par membre : sa fiche, puis tout son historique.",
                                             reason="Casiers des membres (staff)")
        except discord.HTTPException as e:
            print(f"[casiers] forum non créé : {e}")
            return None
        reglages["casiers_forum_id"] = forum.id
        await asave_json(GUILD_SETTINGS_FILE, settings)
        return forum

    # ── la fiche ─────────────────────────────────────────────────────────────

    async def fiche(self, membre) -> discord.Embed:
        e = discord.Embed(title=f"🗂️ {membre.display_name}",
                          description=f"{membre.mention} · `@{membre.name}`",
                          color=membre.color if membre.color.value else discord.Color(COLORS["saphir"]))
        e.set_thumbnail(url=membre.display_avatar.url)
        e.add_field(name="ID", value=f"`{membre.id}`")
        e.add_field(name="Compte créé", value=_date(membre.created_at))
        e.add_field(name="Arrivé sur le serveur", value=_date(getattr(membre, "joined_at", None)))
        roles = [r.mention for r in reversed(getattr(membre, "roles", [])) if not r.is_default()]
        e.add_field(name=f"Rôles ({len(roles)})", value=" ".join(roles)[:1024] if roles else "aucun", inline=False)
        try:
            histo = (await aload_json(HISTO_PSEUDOS, {})).get(str(membre.id), [])
            anciens = list(dict.fromkeys(h["avant"] for h in reversed(histo) if h.get("avant")))
        except Exception:
            anciens = []
        if anciens:
            e.add_field(name="Anciens pseudos", value=" → ".join(f"`{n}`" for n in reversed(anciens[:10])), inline=False)
        try:
            _, totaux, salons = await vocal_store.historique(membre.guild.id, membre.id, 1)
            vocal = f"7 j : **{_duree(totaux[7])}** · 30 j : **{_duree(totaux[30])}**"
            if salons:
                vocal += f"\nSalon favori : {salons[0][0]}"
            e.add_field(name="🎙️ Vocal", value=vocal, inline=False)
        except Exception:
            pass
        if getattr(membre, "premium_since", None):
            e.add_field(name="🚀 Booste depuis", value=_date(membre.premium_since))
        if getattr(membre, "timed_out_until", None) and membre.timed_out_until > discord.utils.utcnow():
            e.add_field(name="⏳ En timeout jusqu'à", value=discord.utils.format_dt(membre.timed_out_until, "f"))
        e.set_footer(text="Fiche mise à jour")
        e.timestamp = discord.utils.utcnow()
        return e

    async def casier(self, membre, creer=True):
        """Le fil du membre (créé s'il manque). None si impossible."""
        async with self._verrou:
            settings, ids = await self._ids(membre.guild)
            fil = membre.guild.get_thread(ids.get(str(membre.id)) or 0)
            if fil is None and ids.get(str(membre.id)):
                try:
                    fil = await membre.guild.fetch_channel(ids[str(membre.id)])
                except discord.HTTPException:
                    fil = None
            if fil is not None or not creer:
                return fil
            forum = await self.forum(membre.guild)
            if forum is None:
                return None
            try:
                cree = await forum.create_thread(name=f"{membre.display_name} · {membre.id}"[:100],
                                                 embed=await self.fiche(membre),
                                                 reason="Casier d'un membre")
            except discord.HTTPException as e:
                print(f"[casiers] casier de {membre} non créé : {e}")
                return None
            settings, ids = await self._ids(membre.guild)
            ids[str(membre.id)] = cree.thread.id
            await asave_json(GUILD_SETTINGS_FILE, settings)
            return cree.thread

    async def maj_fiche(self, membre):
        fil = await self.casier(membre)
        if fil is None:
            return None
        try:
            premier = await fil.fetch_message(fil.id)     # message d'ouverture d'un fil de forum
            await premier.edit(embed=await self.fiche(membre))
            if fil.name != f"{membre.display_name} · {membre.id}"[:100]:
                await fil.edit(name=f"{membre.display_name} · {membre.id}"[:100])
        except discord.HTTPException:
            pass
        return fil

    # ── historique : appelé par cogs/logs.py pour chaque log envoyé ──────────

    async def miroir(self, guild, embed, pieces=None):
        """Recopie un log dans le casier du membre concerné, pièces jointes comprises
        (images d'un message supprimé…). Le log d'origine, lui, reste où il est."""
        uid = membre_concerne(embed)
        if uid is None:
            return
        membre = guild.get_member(uid)
        if membre is None:
            # parti du serveur : on complète son casier s'il en a un, sans en créer
            settings, ids = await self._ids(guild)
            if not ids.get(str(uid)):
                return
            fil = guild.get_thread(ids[str(uid)])
            if fil is None:
                try:
                    fil = await guild.fetch_channel(ids[str(uid)])
                except discord.HTTPException:
                    return
        else:
            if membre.bot:
                return
            fil = await self.casier(membre)
        if fil is None:
            return
        logs = self.bot.get_cog("Logs")
        fichiers = logs._construire(pieces) if (pieces and logs) else []
        try:
            await fil.send(embed=embed.copy(), files=fichiers, allowed_mentions=discord.AllowedMentions.none())
        except discord.HTTPException:
            try:    # trop lourd avec les fichiers : le texte d'abord, les fichiers un par un
                await fil.send(embed=embed.copy(), allowed_mentions=discord.AllowedMentions.none())
                for piece in pieces or []:
                    try:
                        await fil.send(files=logs._construire([piece]))
                    except discord.HTTPException:
                        pass
            except discord.HTTPException as e:
                print(f"[casiers] copie dans le casier {uid} impossible : {e}")

    # ── démarrage, mises à jour, commande ────────────────────────────────────

    @commands.Cog.listener()
    async def on_ready(self):
        if self._remplissage is None or self._remplissage.done():
            self._remplissage = asyncio.create_task(self._remplir())

    async def _remplir(self):
        """Crée les casiers manquants, doucement."""
        for guild in self.bot.guilds:
            if await self.forum(guild) is None:
                continue
            _, ids = await self._ids(guild)
            manquants = [m for m in guild.members if not m.bot and str(m.id) not in ids]
            if manquants:
                print(f"[casiers] {guild.name} : création de {len(manquants)} casier(s)")
            for m in manquants:
                await self.casier(m)
                await asyncio.sleep(DELAI_CREATION)

    @commands.Cog.listener()
    async def on_member_join(self, member):
        if not member.bot:
            await asyncio.sleep(3)       # que le log d'arrivée parte d'abord
            await self.maj_fiche(member)

    @commands.Cog.listener()
    async def on_member_update(self, before, after):
        if after.bot:
            return
        if before.roles != after.roles or before.nick != after.nick or before.display_avatar != after.display_avatar:
            _, ids = await self._ids(after.guild)
            if ids.get(str(after.id)):
                await self.maj_fiche(after)

    @app_commands.command(name="fiche", description="Casier d'un membre : fiche à jour et lien vers tout son historique")
    @app_commands.describe(membre="Le membre")
    @app_commands.default_permissions(moderate_members=True)
    async def fiche_cmd(self, interaction: discord.Interaction, membre: discord.Member):
        await interaction.response.defer(ephemeral=True, thinking=True)
        fil = await self.maj_fiche(membre)
        e = await self.fiche(membre)
        if fil is not None:
            e.add_field(name="📂 Historique complet", value=fil.mention, inline=False)
        await interaction.followup.send(embed=e, ephemeral=True)


def _duree(secondes) -> str:
    s = int(secondes or 0)
    h, s = divmod(s, 3600)
    m = s // 60
    return f"{h} h {m:02d} min" if h else f"{m} min"


async def setup(bot):
    await bot.add_cog(Casiers(bot))
