"""Briques communes à toutes les commandes /setup-*.

Avant ce module, chaque cog recopiait la même séquence : chercher la catégorie, la créer
si absente, appliquer des overwrites, créer le salon, parcourir l'historique pour ne pas
reposter deux fois le message d'explication... soit 9 copies de la création de catégorie
et 24 occurrences du patron « poster une seule fois ». Tout passe désormais par ici.

Chaque helper retourne `(objet, ligne_de_rapport)` : l'objet créé ou trouvé (None si
Discord a refusé), et une ligne prête à afficher dans le rapport de la commande.
"""

import discord

REASON = "Configuration Saphir"


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
