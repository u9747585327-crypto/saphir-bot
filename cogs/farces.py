"""
cogs/farces.py
Commandes pour embêter gentiment les membres, en texte et en vocal.

Texte : /hack, /fakeban, /perroquet, /surnom.
Vocal : /bruitage, /prout, /annonce-vocale, /kidnapping (staff).

Les sons et les annonces (voix « Léo », ElevenLabs) sont générés une fois pour toutes
et livrés dans assets/farces : rien n'est appelé en ligne.

Accès : admins (Gérer le serveur) et propriétaire (Administrateur) uniquement ; les
commandes sont masquées aux autres et revérifiées à chaque appel. /pas-touche reste
ouvert à tous.

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
from cogs.logs import resolve_log_channel
from config import COLORS, GUILD_SETTINGS_FILE, LEVELS_DATA_FILE
from services import message_store
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

# ── /hack : un vrai dossier, mêlé à un faux piratage ──────────────────────────
# RÉEL, et seulement ce que Discord ou le serveur rendent déjà visible : avatar,
# bannière, noms, anciens pseudos (notés par Saphir + journal d'audit du serveur),
# dates de création et d'arrivée, rôles, badges, boost, niveau, activité des 7 derniers
# jours. INVENTÉ : niveau de hack, failles, mot de passe, IP, appareil, fichiers, recherches.
# Jamais : de recherche hors de Discord (ce serait du vrai doxxing), ni de localisation,
# même fausse — à côté de vraies infos, elle aurait l'air authentique.
HISTO_FILE = "data/historique_pseudos.json"
HISTO_MAX = 30
AUDIT_MAX = 5000          # entrées du journal d'audit parcourues au plus (45 jours de toute façon)
BADGES = {
    "staff": "Staff Discord", "partner": "Partenaire Discord", "hypesquad": "HypeSquad Events",
    "bug_hunter": "Chasseur de bugs", "bug_hunter_level_2": "Chasseur de bugs niv. 2",
    "hypesquad_bravery": "HypeSquad Bravery", "hypesquad_brilliance": "HypeSquad Brilliance",
    "hypesquad_balance": "HypeSquad Balance", "early_supporter": "Soutien de la première heure",
    "verified_bot_developer": "Développeur de bot vérifié", "active_developer": "Développeur actif",
    "discord_certified_moderator": "Modérateur certifié",
}
APPAREILS = ["PC portable de 2014 · 47 onglets Chrome ouverts", "iPhone 8 · écran fissuré · 3 % de batterie",
             "PC gamer RGB · 0 jeu terminé", "Samsung en mode économie d'énergie permanent",
             "PC familial partagé avec la petite sœur", "Chromebook de l'école, « emprunté »",
             "PC qui fait un bruit de réacteur de Boeing 747 au démarrage"]
MOTS_DE_PASSE = ["iloveyou123", "motdepasse", "azerty123", "jaimemamaman", "MonChatSappelleKiwi",
                 "123soleil", "pizza4ever", "jesuisleplusbeau", "password1", "medor2010"]
NIVEAUX_HACK = [("Débutant", 23), ("Intermédiaire", 57), ("Expert", 88), ("Élite", 100)]
FAILLES = ["Mot de passe écrit sur un post-it collé à l'écran", "Clique sur toutes les pubs « Vous avez gagné un iPhone »",
           "Même mot de passe depuis 2012", "Webcam sans cache depuis 3 ans",
           "A prêté son compte Netflix à 14 personnes", "Accepte tous les cookies sans lire",
           "Wi-Fi « Livebox-Mamie » sans mot de passe",
           "A cliqué sur « Télécharger plus de RAM gratuitement »",
           "Mot de passe : azerty123, ou le prénom de son chien",
           "A cru qu'un prince nigérian allait vraiment lui transférer un héritage",
           "Scotch sur la webcam, mais micro allumé depuis 4 jours"]
DONNEES_VOLEES = ["14 Go de selfies ratés", "son historique YouTube (« tuto danse TikTok » ×47)",
                  "3 brouillons de déclaration d'amour", "sa playlist « motivation » 100 % Jul",
                  "un dossier « Devoirs » qui n'en contient aucun", "ses notes du bac (on n'en parlera pas)",
                  "« Nouveau dossier (42) », totalement vide", "35 vidéos de chutes ratées en trottinette",
                  "« Projets sérieux » : 50 Go de mèmes", "mots_de_passe_ne_pas_ouvrir.txt, sur le bureau"]
RECHERCHES = ["comment devenir drôle", "pourquoi personne me répond sur discord",
              "est-ce que les pâtes c'est un légume", "comment gagner en ranked sans jouer",
              "tuto avoir des amis", "mon chat me juge est-ce normal", "c'est grave de dormir 14h",
              "acheter des abonnés pas cher", "comment effacer son historique",
              "gemmes gratuites brawl stars sans virus", "pourquoi mon chat me fixe quand je dors",
              "excuse crédible pour annuler une sortie à la dernière minute",
              "peut-on cuire des pâtes dans une bouilloire"]
ACTIVITES = ["A supprimé un message vocal WhatsApp beaucoup trop tard",
             "A liké une photo de 2017 en stalkant, puis l'a retirée",
             "A répondu « mdr » à un message triste par réflexe",
             "A envoyé « je suis en route » depuis son lit",
             "A relu 14 fois un message avant de l'envoyer, puis l'a supprimé"]
DANGEROSITES = ["Inoffensif · panique quand il n'y a plus de Wi-Fi",
                "Faible · se fait battre par les captchas",
                "Négligeable · demande à sa mère pour changer de mot de passe",
                "Nulle · croit que « incognito » le rend invisible"]
VERT, ROUGE, JAUNE, BLEU, CYAN, GRIS, GRAS, RAZ = (
    "\u001b[0;32m", "\u001b[0;31m", "\u001b[0;33m", "\u001b[0;34m", "\u001b[0;36m", "\u001b[0;30m",
    "\u001b[1;37m", "\u001b[0m")
FAI = ["Orange", "Free", "SFR", "Bouygues Telecom"]
OCTETS_FAI = [78, 79, 80, 82, 83, 86, 88, 90, 92, 109, 176, 185, 212]


def _ip():
    return f"{random.choice(OCTETS_FAI)}.{random.randint(1, 254)}.{random.randint(1, 254)}.{random.randint(2, 254)}"


def _barre(pourcent: int) -> str:
    plein = pourcent * 20 // 100
    return f"[{'█' * plein}{'░' * (20 - plein)}] {pourcent:3d}%"


def inventer(d: dict, membre) -> dict:
    """Les fausses infos de hacker, tirées une fois pour que le terminal et la fiche
    affichent les mêmes."""
    d.update(
        ip=_ip(), serveur=_ip(), fai=random.choice(FAI), appareil=random.choice(APPAREILS),
        recherches=random.sample(RECHERCHES, 3), mdp=random.choice(MOTS_DE_PASSE),
        niveau_hack=random.choice(NIVEAUX_HACK), failles=random.sample(FAILLES, 3),
        volees=random.sample(DONNEES_VOLEES, 3), activite_recente=random.choice(ACTIVITES),
        dangerosite=random.choice(DANGEROSITES),
    )
    return d


def piratage(membre, d: dict) -> list:
    """Les images successives du terminal : liste de (attente en s, lignes)."""
    images, l = [], [f"{VERT}root@saphir{RAZ}:{BLEU}~{RAZ}# ./breach --target {membre.name}"]

    def image(attente, *nouvelles):
        l.extend(nouvelles)
        images.append((attente, list(l)))

    profil = ["avatar"] + (["bannière"] if d.get("banniere") else []) + \
             ([f"{len(d['badges'])} badge(s)"] if d.get("badges") else [])
    image(1.2, f"{CYAN}[*]{RAZ} Résolution du compte Discord…",
          f"    ID {membre.id} · créé le {membre.created_at:%d/%m/%Y}")
    image(1.3, f"{VERT}[+]{RAZ} Profil récupéré : {', '.join(profil)}")
    n = len(d.get("pseudos") or [])
    image(1.3, f"{VERT}[+]{RAZ} Historique : {n} ancien(s) pseudo(s) retrouvé(s)" if n
          else f"{JAUNE}[-]{RAZ} Historique : aucun ancien pseudo (il se cache bien)")
    activite = []
    if d.get("messages"):
        activite.append(f"{d['messages']} messages en 7 j")
    if d.get("niveau") is not None:
        activite.append(f"niveau {d['niveau']}")
    image(1.3, f"{CYAN}[*]{RAZ} Analyse d'activité : {', '.join(activite) or 'aucune trace'}")
    image(1.5, f"{CYAN}[*]{RAZ} Corrélation adresse IP… {VERT}{d['ip']}{RAZ} ({d['fai']})")
    l.append(f"{CYAN}[*]{RAZ} Brute-force du mot de passe {_barre(0)}")
    for pct in (31, 74):
        l[-1] = f"{CYAN}[*]{RAZ} Brute-force du mot de passe {_barre(pct)}"
        images.append((1.1, list(l)))
    l[-1] = f"{CYAN}[*]{RAZ} Brute-force du mot de passe {_barre(100)}"
    image(1.1, f"{VERT}[+]{RAZ} Mot de passe : {JAUNE}{d['mdp']}{RAZ}")
    image(1.3, f"{ROUGE}[!]{RAZ} {len(d['failles'])} failles critiques exploitées")
    image(1.3, f"{GRAS}[✓] Dossier compilé. Envoi vers {d['serveur']}.{RAZ}")
    return images


PIED_HACK = "Résultat 100% fictif pour rire entre potes"
COULEUR_PANEL = 0x8B1E1E      # rouge sombre : plus sobre que le rouge vif des alertes


def carte_dossier(membre, d: dict) -> discord.ui.LayoutView:
    """La fiche finale, en Components V2 : en-tête avec la photo de profil, le vrai
    profil, puis le piratage inventé présenté comme un dump de terminal."""
    fmt = discord.utils.format_dt
    vue = discord.ui.LayoutView(timeout=None)
    carte = discord.ui.Container(accent_colour=discord.Colour(COULEUR_PANEL))

    nom_niveau, pct = d["niveau_hack"]
    carte.add_item(discord.ui.Section(
        f"## PANEL D'INTRUSION\n### {membre.display_name}\n"
        f"-# Cible @{membre.name} · ID {membre.id} · session ouverte <t:{int(time.time())}:R>",
        accessory=discord.ui.Thumbnail(membre.display_avatar.url),
    ))
    if d.get("banniere"):
        carte.add_item(discord.ui.MediaGallery(discord.MediaGalleryItem(d["banniere"])))
    carte.add_item(discord.ui.TextDisplay(
        f"**STATUT** `ACCÈS ROOT` · **COMPROMISSION** `{_barre(pct)}` {nom_niveau}\n"
        f"**DANGEROSITÉ** {d['dangerosite']}"))
    carte.add_item(discord.ui.Separator(spacing=discord.SeparatorSpacing.large))

    # ── le vrai ──
    profil = ["### PROFIL",
              f"**Compte créé** · {fmt(membre.created_at, 'D')} ({fmt(membre.created_at, 'R')})"]
    if getattr(membre, "joined_at", None):
        profil.append(f"**Sur le serveur** · depuis le {fmt(membre.joined_at, 'D')} ({fmt(membre.joined_at, 'R')})")
    roles = [r.mention for r in reversed(membre.roles) if not r.is_default()][:6]
    if roles:
        profil.append(f"**Rôles** · {' '.join(roles)}")
    pseudos = d.get("pseudos") or []
    if pseudos:    # du plus ancien au pseudo actuel
        frise = " → ".join(f"`{p}`" for p in reversed(pseudos))
        profil.append(f"**Anciens pseudos** · {frise} → **{membre.display_name}**")
    else:
        profil.append("**Anciens pseudos** · aucun retrouvé")
    if d.get("badges"):
        profil.append(f"**Badges** · {', '.join(d['badges'])}")
    carte.add_item(discord.ui.TextDisplay("\n".join(profil)))

    activite = []
    if d.get("niveau") is not None:
        activite += [f"Niveau **{d['niveau']}**", f"**{d['vocal_h']:.1f} h** en vocal"]
    if d.get("messages"):
        activite.append(f"**{d['messages']}** messages cette semaine"
                        + (f" (surtout <#{d['salon']}>)" if d.get("salon") else ""))
    if d.get("dernier"):
        activite.append(f"vu <t:{int(d['dernier'])}:R>")
    if getattr(membre, "premium_since", None):
        activite.append(f"booste depuis le {fmt(membre.premium_since, 'D')}")
    carte.add_item(discord.ui.TextDisplay(
        "### ACTIVITÉ\n" + (" · ".join(activite) or "Un fantôme : aucune trace.")))
    carte.add_item(discord.ui.Separator(spacing=discord.SeparatorSpacing.large))

    # ── l'inventé ──
    def numeros(lignes):
        return "\n".join(f"`{i:02d}` {l}" for i, l in enumerate(lignes, 1))

    carte.add_item(discord.ui.TextDisplay("### FAILLES EXPLOITÉES\n" + numeros(d["failles"])))
    carte.add_item(discord.ui.TextDisplay("### FICHIERS EXTRAITS\n" + numeros(d["volees"])))
    carte.add_item(discord.ui.TextDisplay(
        "### HISTORIQUE DE RECHERCHE\n" + "\n".join(f"`>` « {r} »" for r in d["recherches"])))
    machine = [
        f"{GRIS}machine       {RAZ}{d['appareil']}",
        f"{GRIS}adresse IP    {RAZ}{VERT}{d['ip']}{RAZ} ({d['fai']})",
        f"{GRIS}mot de passe  {RAZ}{JAUNE}{d['mdp']}{RAZ}",
        f"{GRIS}dernière act. {RAZ}{d['activite_recente']}",
    ]
    carte.add_item(discord.ui.TextDisplay("### MACHINE CIBLÉE\n" + bloc_terminal(machine)))
    carte.add_item(discord.ui.Separator())
    carte.add_item(discord.ui.TextDisplay(f"-# {PIED_HACK}"))
    vue.add_item(carte)
    return vue


def bloc_terminal(lignes: list) -> str:
    return "```ansi\n" + "\n".join(lignes) + "\n```"
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

    # ── accès : admins et propriétaire ───────────────────────────────────────

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        """Les farces sont réservées aux admins et au propriétaire : permission
        Administrateur (rôle Owner) ou Gérer le serveur (rôle Admin). Le menu / les
        masque déjà aux autres (default_permissions), mais un admin peut rouvrir l'accès
        dans les réglages d'intégration de Discord : on revérifie donc ici.
        /pas-touche reste ouvert à tous : c'est ce qui permet de se protéger."""
        if getattr(interaction.command, "name", "") == "pas-touche":
            return True
        droits = interaction.user.guild_permissions
        return droits.administrator or droits.manage_guild or interaction.user.id == interaction.guild.owner_id

    # ── anonymat ─────────────────────────────────────────────────────────────
    # Discord affiche « X used /commande » au-dessus de toute RÉPONSE à une commande.
    # On répond donc en privé au lanceur, et la farce part comme un message normal du
    # bot, qui ne porte aucun nom.

    async def _discret(self, interaction: discord.Interaction):
        await interaction.response.send_message("🤫 C'est parti. Personne ne verra que c'est toi.", ephemeral=True)

    async def _tracer(self, interaction: discord.Interaction, commande: str, cible=None, lieu=None):
        """Anonyme pour les membres, mais pas pour le staff : chaque farce est notée
        dans le salon de logs modération, au cas où quelqu'un en abuse."""
        try:
            salon = await resolve_log_channel(self.bot, interaction.guild, "moderation")
            if salon is None:
                return
            lignes = [f"**Par** : {interaction.user.mention}", f"**Commande** : `/{commande}`"]
            if cible is not None:
                lignes.append(f"**Cible** : {cible.mention}")
            lignes.append(f"**Salon** : {(lieu or interaction.channel).mention}")
            embed = discord.Embed(title="🎭 Farce anonyme", description="\n".join(lignes),
                                  color=discord.Color(COLORS["grey"]))
            embed.timestamp = discord.utils.utcnow()
            await salon.send(embed=embed)
        except Exception as e:
            print(f"[farces] trace non envoyée : {e}")

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
    @app_commands.default_permissions(manage_guild=True)
    @app_commands.describe(membre="La victime")
    async def hack(self, interaction: discord.Interaction, membre: discord.Member):
        if not await self._peut(interaction, membre):
            return
        await self._discret(interaction)
        await self._tracer(interaction, "hack", membre)
        entete = f"💻 {membre.mention}"
        invite = f"{VERT}root@saphir{RAZ}:{BLEU}~{RAZ}# ./breach --target {membre.name}"
        try:
            msg = await interaction.channel.send(f"{entete}\n{bloc_terminal([invite, f'{CYAN}[*]{RAZ} Initialisation…'])}")
        except discord.HTTPException:
            return
        d = inventer(await self._dossier(membre), membre)   # pendant que le terminal s'initialise
        try:
            for attente, lignes in piratage(membre, d):
                await asyncio.sleep(attente)
                await msg.edit(content=f"{entete}\n{bloc_terminal(lignes)}")
            await asyncio.sleep(1.2)
            # Une carte Components V2 ne peut pas cohabiter avec du texte : elle part en
            # message à part, sous le terminal, sans repinger la victime.
            await interaction.channel.send(view=carte_dossier(membre, d),
                                           allowed_mentions=discord.AllowedMentions.none())
        except discord.HTTPException:
            return

    async def _dossier(self, membre) -> dict:
        """Le vrai : ce que Discord et le serveur rendent déjà visible. Chaque source
        est facultative ; une qui échoue laisse simplement sa case vide."""
        guild = membre.guild
        d = {"pseudos": [], "banniere": None, "niveau": None, "vocal_h": 0.0,
             "messages": None, "salon": None, "dernier": None, "badges": []}
        noms = []
        try:
            histo = (await aload_json(HISTO_FILE, {})).get(str(membre.id), [])
            noms += [h["avant"] for h in reversed(histo) if h.get("avant")]
        except Exception:
            pass
        try:  # pseudos portés sur ce serveur : le journal d'audit ENTIER (45 jours)
            # Discord ne filtre pas le journal par cible : il faut tout parcourir. Lire
            # seulement les 300 dernières entrées ratait tout changement un peu ancien
            # (1 378 entrées member_update en six semaines sur La Famii).
            if guild.me.guild_permissions.view_audit_log:
                trouves = []
                async for e in guild.audit_logs(limit=AUDIT_MAX, action=discord.AuditLogAction.member_update):
                    if getattr(e.target, "id", None) != membre.id:
                        continue
                    if hasattr(e.changes.before, "nick") or hasattr(e.changes.after, "nick"):
                        trouves.append({"quoi": "pseudo", "avant": getattr(e.changes.before, "nick", None),
                                        "apres": getattr(e.changes.after, "nick", None),
                                        "quand": e.created_at.timestamp()})
                noms += [n for t in trouves for n in (t["apres"], t["avant"]) if n]
                if trouves:
                    await self._memoriser(membre.id, trouves)
        except Exception:
            pass
        actuels = {membre.name, getattr(membre, "global_name", None), membre.nick}
        for n in noms:
            if n not in actuels and n not in d["pseudos"]:
                d["pseudos"].append(n)
        d["pseudos"] = d["pseudos"][:8]
        try:
            utilisateur = await self.bot.fetch_user(membre.id)
            if utilisateur.banner:
                d["banniere"] = utilisateur.banner.url
        except Exception:
            pass
        try:
            niveau = (await aload_json(LEVELS_DATA_FILE, {})).get(str(guild.id), {}).get(str(membre.id))
            if niveau:
                d["niveau"], d["vocal_h"] = niveau.get("level", 0), niveau.get("voice_seconds", 0) / 3600
        except Exception:
            pass
        try:
            d["messages"], d["salon"], d["dernier"] = await message_store.stats_auteur(guild.id, membre.id)
        except Exception:
            pass
        try:
            d["badges"] = [BADGES[nom] for nom, actif in membre.public_flags if actif and nom in BADGES]
        except Exception:
            pass
        return d

    # Historique des noms : Discord n'en fournit aucun, Saphir le tient lui-même.
    async def _memoriser(self, user_id: int, trouves: list):
        """Garde les pseudos retrouvés dans le journal d'audit : Discord l'efface au bout
        de 45 jours, Saphir les conserve au-delà."""
        data = await aload_json(HISTO_FILE, {})
        histo = data.get(str(user_id), [])
        deja = {(h.get("avant"), h.get("apres"), int(h.get("quand", 0))) for h in histo}
        for t in trouves:
            if (t["avant"], t["apres"], int(t["quand"])) not in deja:
                histo.append(t)
        histo.sort(key=lambda h: h.get("quand", 0))
        data[str(user_id)] = histo[-HISTO_MAX:]
        await asave_json(HISTO_FILE, data)

    async def _noter_nom(self, user_id: int, quoi: str, avant, apres):
        if not avant or avant == apres:
            return
        data = await aload_json(HISTO_FILE, {})
        histo = data.get(str(user_id), [])
        histo.append({"quoi": quoi, "avant": avant, "apres": apres, "quand": time.time()})
        data[str(user_id)] = histo[-HISTO_MAX:]
        await asave_json(HISTO_FILE, data)

    @commands.Cog.listener()
    async def on_member_update(self, before: discord.Member, after: discord.Member):
        if before.nick != after.nick:
            await self._noter_nom(after.id, "pseudo", before.nick, after.nick)

    @commands.Cog.listener()
    async def on_user_update(self, before: discord.User, after: discord.User):
        if before.name != after.name:
            await self._noter_nom(after.id, "nom d'utilisateur", before.name, after.name)
        if before.global_name != after.global_name:
            await self._noter_nom(after.id, "nom affiché", before.global_name, after.global_name)

    @app_commands.command(name="fakeban", description="Bannit un membre… pour de faux")
    @app_commands.default_permissions(manage_guild=True)
    @app_commands.describe(membre="La victime")
    async def fakeban(self, interaction: discord.Interaction, membre: discord.Member):
        if not await self._peut(interaction, membre):
            return
        embed = discord.Embed(
            title="🔨 Bannissement",
            description=f"{membre.mention} a été **banni** du serveur.\n**Raison** : {random.choice(RAISONS_BAN)}",
            color=discord.Color(COLORS["danger"]),
        )
        embed.set_footer(text="Modération Saphir")
        await self._discret(interaction)
        await self._tracer(interaction, "fakeban", membre)
        try:
            msg = await interaction.channel.send(content=membre.mention, embed=embed)
            await asyncio.sleep(6)
            embed.title = "🔨 Bannissement… ou pas"
            embed.description += "\n\n😭 **C'était une blague.** Pour cette fois."
            embed.color = discord.Color(COLORS["success"])
            await msg.edit(embed=embed)
        except discord.HTTPException:
            pass

    @app_commands.command(name="perroquet", description="Pendant 1 min, Saphir répète ce qu'il écrit en mOdE mOqUeUr")
    @app_commands.default_permissions(manage_guild=True)
    @app_commands.describe(membre="La victime")
    async def perroquet(self, interaction: discord.Interaction, membre: discord.Member):
        if not await self._peut(interaction, membre):
            return
        self._perroquets[(interaction.guild.id, membre.id)] = {
            "salon": interaction.channel.id,
            "fin": time.monotonic() + DUREE_PERROQUET,
            "restant": REPETITIONS_PERROQUET,
        }
        await self._discret(interaction)
        await self._tracer(interaction, "perroquet", membre)
        try:
            await interaction.channel.send(
                f"🦜 Le perroquet s'est posé sur l'épaule de {membre.mention}. Pendant une minute, "
                "tout ce qu'il écrit ici sera répété… à notre façon."
            )
        except discord.HTTPException:
            pass

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
    @app_commands.default_permissions(manage_guild=True)
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
        await self._discret(interaction)
        await self._tracer(interaction, "surnom", membre)
        try:
            await interaction.channel.send(
                f"🏷️ {membre.mention} s'appelle désormais **{nouveau}**. Retour à la normale dans 10 minutes.")
        except discord.HTTPException:
            pass

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
        await self._discret(interaction)
        commande = getattr(getattr(interaction, "command", None), "name", None) or "bruitage"
        await self._tracer(interaction, commande, lieu=voix.channel)
        try:
            await interaction.channel.send(f"{libelle} dans {voix.channel.mention}…")
        except discord.HTTPException:
            pass
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
    @app_commands.default_permissions(manage_guild=True)
    @app_commands.describe(son="Le bruitage")
    @app_commands.choices(son=[app_commands.Choice(name=v, value=k) for k, v in BRUITAGES.items()])
    async def bruitage(self, interaction: discord.Interaction, son: app_commands.Choice[str]):
        chemin = os.path.join(FARCES_DIR, "bruitages", f"{son.value}.ogg")
        await self._jouer_en_vocal(interaction, chemin if os.path.exists(chemin) else None, son.name)

    @app_commands.command(name="prout", description="Le grand classique, dans ton salon vocal")
    @app_commands.default_permissions(manage_guild=True)
    async def prout(self, interaction: discord.Interaction):
        chemin = os.path.join(FARCES_DIR, "bruitages", "pet.ogg")
        await self._jouer_en_vocal(interaction, chemin if os.path.exists(chemin) else None, "💨 Prout")

    @app_commands.command(name="annonce-vocale", description="Une annonce absurde de Saphir Radio dans ton vocal")
    @app_commands.default_permissions(manage_guild=True)
    async def annonce_vocale(self, interaction: discord.Interaction):
        await self._jouer_en_vocal(interaction, fichier_au_hasard("annonces"), "📢 Annonce spéciale")

    @app_commands.command(name="kidnapping", description="Embarque un membre dans un autre vocal pendant 15 s")
    @app_commands.default_permissions(manage_guild=True)
    @app_commands.describe(membre="La victime")
    async def kidnapping(self, interaction: discord.Interaction, membre: discord.Member):
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
        await self._discret(interaction)
        await self._tracer(interaction, "kidnapping", membre, lieu=depart)
        msg = None
        try:
            msg = await interaction.channel.send(
                f"🚐 {membre.mention} a été **kidnappé** et emmené dans {planque.mention} ! "
                f"Libération dans {DUREE_KIDNAPPING} secondes… normalement.")
        except discord.HTTPException:
            pass
        await asyncio.sleep(DUREE_KIDNAPPING)
        # on ne le ramène que s'il est toujours là où on l'a laissé
        if membre.voice is not None and membre.voice.channel == planque and guild.get_channel(depart.id):
            try:
                await membre.move_to(depart, reason="Fin du /kidnapping")
                if msg is not None:
                    await msg.edit(content=f"🕊️ {membre.mention} a été libéré et ramené dans {depart.mention}. "
                                           "Plus de peur que de mal.")
            except discord.HTTPException:
                pass

    async def cog_app_command_error(self, interaction: discord.Interaction, error: app_commands.AppCommandError):
        await handle_app_error(interaction, error, command_label="une farce",
                               perm_message="🔒 Les farces sont réservées aux admins et au propriétaire du serveur.")


async def setup(bot):
    await bot.add_cog(Farces(bot))
