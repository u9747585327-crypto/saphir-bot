"""Briques communes à toutes les commandes /setup-*.

Avant ce module, chaque cog recopiait la même séquence : chercher la catégorie, la créer
si absente, appliquer des overwrites, créer le salon, parcourir l'historique pour ne pas
reposter deux fois le message d'explication... soit 9 copies de la création de catégorie
et 24 occurrences du patron « poster une seule fois ». Tout passe désormais par ici.

Chaque helper retourne `(objet, ligne_de_rapport)` : l'objet créé ou trouvé (None si
Discord a refusé), et une ligne prête à afficher dans le rapport de la commande.
"""

import re
import unicodedata

import discord

REASON = "Configuration Saphir"


def normalize(text: str) -> str:
    """Minuscules, sans accents ni emoji ni ponctuation — pour reconnaître un salon/rôle
    dont le nom a changé de style, de casse ou d'emoji sans perdre son sens. Partagé avec
    cogs/diagnostic.py (même logique de détection tolérante)."""
    text = unicodedata.normalize("NFKD", text)
    text = "".join(c for c in text if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9]", "", text.lower())


def _find_by_keywords(items, keywords):
    """Premier objet (catégorie/salon) dont le nom normalisé contient un des mots-clés."""
    normalized_keywords = [normalize(k) for k in keywords if k]
    for item in items:
        name = normalize(item.name)
        if any(kw and kw in name for kw in normalized_keywords):
            return item
    return None


def readonly_overwrites(guild: discord.Guild, *extra_roles: discord.Role) -> dict:
    """Lecture seule pour @everyone (et pour les rôles supplémentaires donnés, utile
    quand un rôle a le droit d'écrire ailleurs dans la catégorie — ex. Exilé)."""
    overwrites = {guild.default_role: discord.PermissionOverwrite(send_messages=False)}
    for role in extra_roles:
        if role is not None:
            overwrites[role] = discord.PermissionOverwrite(view_channel=True, send_messages=False)
    return overwrites


def hidden_overwrites(guild: discord.Guild, *visible_roles: discord.Role) -> dict:
    """Masqué pour @everyone, visible et inscriptible pour les rôles donnés."""
    overwrites = {guild.default_role: discord.PermissionOverwrite(view_channel=False)}
    for role in visible_roles:
        if role is not None:
            overwrites[role] = discord.PermissionOverwrite(view_channel=True, send_messages=True)
    return overwrites


async def ensure_role(guild, name, *, color=None, hoist=False, permissions=None, reason=REASON):
    role = discord.utils.get(guild.roles, name=name)
    if role is not None:
        return role, f"= Rôle déjà présent : {name}"
    try:
        kwargs = {"name": name, "hoist": hoist, "mentionable": False, "reason": reason}
        if color is not None:
            kwargs["color"] = discord.Color(color)
        if permissions is not None:
            kwargs["permissions"] = permissions
        role = await guild.create_role(**kwargs)
        return role, f"✅ Rôle créé : {name}"
    except discord.Forbidden:
        return None, f"❌ Rôle refusé (permissions) : {name}"


async def ensure_category(guild, name, *, overwrites=None, reason=REASON):
    category = discord.utils.get(guild.categories, name=name)
    try:
        if category is None:
            category = await guild.create_category(name, overwrites=overwrites or {}, reason=reason)
            return category, f"✅ Catégorie créée : {name}"
        if overwrites:
            await category.edit(overwrites=overwrites, reason=reason)
            return category, f"🔄 Catégorie mise à jour : {name}"
        return category, f"= Catégorie déjà présente : {name}"
    except discord.Forbidden:
        return None, f"❌ Catégorie refusée (permissions) : {name}"


async def ensure_text_channel(guild, name, *, category=None, overwrites=None, reason=REASON):
    channel = discord.utils.get(guild.text_channels, name=name)
    try:
        if channel is None:
            channel = await guild.create_text_channel(
                name, category=category, overwrites=overwrites or {}, reason=reason
            )
            return channel, f"✅ Salon créé : {name}"

        if category is not None and channel.category != category:
            await channel.edit(category=category, reason=reason)
        if overwrites:
            await channel.edit(overwrites=overwrites, reason=reason)
        return channel, f"= Salon déjà présent : {name}"
    except discord.Forbidden:
        return None, f"❌ Salon refusé (permissions) : {name}"


async def ensure_voice_channel(guild, name, *, category=None, overwrites=None, reason=REASON):
    channel = discord.utils.get(guild.voice_channels, name=name)
    try:
        if channel is None:
            channel = await guild.create_voice_channel(
                name, category=category, overwrites=overwrites or {}, reason=reason
            )
            return channel, f"✅ Salon vocal créé : {name}"
        if overwrites:
            await channel.edit(overwrites=overwrites, reason=reason)
        return channel, f"🔄 Salon vocal mis à jour : {name}"
    except discord.Forbidden:
        return None, f"❌ Salon vocal refusé (permissions) : {name}"


async def adopt_role(guild, name, *, color=None, hoist=False, permissions=None, reason=REASON):
    """ensure_role, mais reconnaît un rôle existant même si son nom a changé de style/casse
    (ex : « Fondateur », « 𝗙𝗼𝗻𝗱𝗮𝘁𝗲𝘂𝗿 », « 「🜲・👑 𝗙𝗼𝗻𝗱𝗮𝘁𝗲𝘂𝗿」 » ont le même nom normalisé)
    et le RENOMME au nom canonique — donc pas de doublon et aucun membre perdu. La
    correspondance est une égalité EXACTE du nom normalisé (pas un « contient »), pour ne
    pas confondre « Admin » avec « Admin Chat »."""
    target = normalize(name)
    role = discord.utils.get(guild.roles, name=name)
    if role is None:
        for r in guild.roles:
            if not r.managed and r.name != "@everyone" and normalize(r.name) == target:
                role = r
                break
    try:
        if role is None:
            kwargs = {"name": name, "hoist": hoist, "mentionable": False, "reason": reason}
            if color is not None:
                kwargs["color"] = discord.Color(color)
            if permissions is not None:
                kwargs["permissions"] = permissions
            role = await guild.create_role(**kwargs)
            return role, f"✅ Rôle créé : {name}"
        edits = {"hoist": hoist, "reason": reason}
        renamed = role.name != name
        if renamed:
            edits["name"] = name
        if color is not None:
            edits["color"] = discord.Color(color)
        if permissions is not None:
            edits["permissions"] = permissions
        await role.edit(**edits)
        return role, (f"🔁 Rôle adopté et renommé : {name}" if renamed else f"🔄 Rôle mis à jour : {name}")
    except discord.Forbidden:
        return None, f"❌ Rôle refusé (permissions) : {name}"


async def adopt_category(guild, name, *, keywords=(), overwrites=None, reason=REASON):
    """Comme ensure_category, mais si aucune catégorie ne porte le nom exact, on cherche une
    catégorie existante proche (par mot-clé) et on la RENOMME vers `name` au lieu d'en créer
    une seconde. Évite les doublons quand une catégorie a juste un autre emoji/style."""
    existing = discord.utils.get(guild.categories, name=name)
    if existing is None and keywords:
        candidate = _find_by_keywords(guild.categories, keywords)
        if candidate is not None:
            try:
                await candidate.edit(name=name, reason=reason)
                if overwrites:
                    await candidate.edit(overwrites=overwrites, reason=reason)
                return candidate, f"🔁 Catégorie adoptée et renommée : {name}"
            except discord.Forbidden:
                return None, f"❌ Catégorie non renommable (permissions) : {name}"
    return await ensure_category(guild, name, overwrites=overwrites, reason=reason)


async def adopt_text_channel(guild, name, *, category=None, keywords=(), overwrites=None, reason=REASON):
    """ensure_text_channel + adoption par mot-clé (renomme un salon proche au lieu de dupliquer),
    et déplacement dans `category`. On ne cherche le candidat que dans la catégorie cible si
    elle est fournie, sinon partout — pour ne pas happer un salon d'une autre section."""
    existing = discord.utils.get(guild.text_channels, name=name)
    if existing is None and keywords:
        pool = category.text_channels if category is not None else guild.text_channels
        candidate = _find_by_keywords(pool, keywords)
        if candidate is not None:
            try:
                await candidate.edit(name=name, reason=reason)
                if category is not None and candidate.category != category:
                    await candidate.edit(category=category, reason=reason)
                if overwrites:
                    await candidate.edit(overwrites=overwrites, reason=reason)
                return candidate, f"🔁 Salon adopté et renommé : {name}"
            except discord.Forbidden:
                return None, f"❌ Salon non renommable (permissions) : {name}"
    return await ensure_text_channel(guild, name, category=category, overwrites=overwrites, reason=reason)


async def post_once(channel, bot_user_id: int, embed: discord.Embed, marker: str) -> bool:
    """Poste `embed` seulement s'il n'a pas déjà été posté dans ce salon. Le repère est
    le texte du footer, écrit ici même — relancer un /setup-* ne duplique donc rien.
    Retourne True si le message vient d'être posté."""
    if channel is None:
        return False
    embed.set_footer(text=marker)
    try:
        async for msg in channel.history(limit=15):
            if msg.author.id == bot_user_id and msg.embeds and msg.embeds[0].footer.text == marker:
                return False
        await channel.send(embed=embed)
        return True
    except discord.HTTPException:
        return False
