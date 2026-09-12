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


def _find_equivalent(items, names):
    """Premier objet dont le nom normalisé est ÉGAL à l'un des noms donnés (le nom canonique
    + ses alias). Égalité stricte et non « contient » : « niveaux » ≠ « infos-niveaux », mais
    « niveaux », « 📊・niveaux » et « 「 🎉 」 niveaux » ont tous le même nom normalisé, donc
    sont reconnus comme le même salon quel que soit leur style/emoji."""
    targets = {normalize(n) for n in names if n and normalize(n)}
    for item in items:
        if normalize(item.name) in targets:
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
    """Comme ensure_category, mais reconnaît une catégorie existante qui porte le même nom à
    un style/emoji près (nom normalisé égal à `name` ou à un des `keywords` alias) et la
    RENOMME vers `name` — pas de doublon. Ex : `keywords=["appel"]` fait adopter « 🎧 · Appel »
    comme « 🔊 VOCAL »."""
    candidate = _find_equivalent(guild.categories, [name, *keywords])
    if candidate is not None:
        try:
            edits = {"reason": reason}
            renamed = candidate.name != name
            if renamed:
                edits["name"] = name
            if overwrites:
                edits["overwrites"] = overwrites
            await candidate.edit(**edits)
            return candidate, (f"🔁 Catégorie adoptée : {name}" if renamed else f"= Catégorie déjà présente : {name}")
        except discord.Forbidden:
            return None, f"❌ Catégorie non modifiable (permissions) : {name}"
    return await ensure_category(guild, name, overwrites=overwrites, reason=reason)


async def adopt_text_channel(guild, name, *, category=None, keywords=(), overwrites=None, reason=REASON):
    """ensure_text_channel + adoption : reconnaît un salon existant de même nom à un style/emoji
    près (nom normalisé égal à `name` ou à un alias), le RENOMME et le DÉPLACE dans `category`
    — pas de doublon, historique gardé. La recherche est sur tout le serveur (le salon peut
    être encore dans son ancienne catégorie)."""
    candidate = _find_equivalent(guild.text_channels, [name, *keywords])
    if candidate is not None:
        try:
            edits = {"reason": reason}
            renamed = candidate.name != name
            if renamed:
                edits["name"] = name
            if category is not None and candidate.category != category:
                edits["category"] = category
            if overwrites:
                edits["overwrites"] = overwrites
            if len(edits) > 1:
                await candidate.edit(**edits)
            return candidate, (f"🔁 Salon adopté : {name}" if renamed else f"= Salon déjà présent : {name}")
        except discord.Forbidden:
            return None, f"❌ Salon non modifiable (permissions) : {name}"
    return await ensure_text_channel(guild, name, category=category, overwrites=overwrites, reason=reason)


async def adopt_voice_channel(guild, name, *, category=None, keywords=(), overwrites=None, reason=REASON):
    """ensure_voice_channel + adoption par nom normalisé (comme adopt_text_channel)."""
    candidate = _find_equivalent(guild.voice_channels, [name, *keywords])
    if candidate is not None:
        try:
            edits = {"reason": reason}
            renamed = candidate.name != name
            if renamed:
                edits["name"] = name
            if category is not None and candidate.category != category:
                edits["category"] = category
            if overwrites:
                edits["overwrites"] = overwrites
            if len(edits) > 1:
                await candidate.edit(**edits)
            return candidate, (f"🔁 Salon vocal adopté : {name}" if renamed else f"= Salon vocal déjà présent : {name}")
        except discord.Forbidden:
            return None, f"❌ Salon vocal non modifiable (permissions) : {name}"
    return await ensure_voice_channel(guild, name, category=category, overwrites=overwrites, reason=reason)


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
