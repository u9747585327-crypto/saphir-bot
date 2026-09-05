import discord
from discord import app_commands
from discord.ext import commands

from config import HONEYPOT_CHANNEL_NAME, COLORS


def build_honeypot_embed(member: discord.Member) -> discord.Embed:
    embed = discord.Embed(
        title="🍯 Salon piège déclenché",
        description=(
            f"{member.mention} a écrit dans un salon où il ne faut **jamais** envoyer de message "
            "et a été expulsé du serveur.\n\n"
            "Ce salon n'existe que pour repérer les comptes automatisés (bots, raids)."
        ),
        color=discord.Color(COLORS["danger"]),
    )
    embed.set_footer(text="Saphir · Honeypot 🍯")
    return embed


class Honeypot(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(
        name="setup-honeypot",
        description="Crée (ou vérifie) le salon piège anti-bot",
    )
    @app_commands.checks.has_permissions(administrator=True)
    async def setup_honeypot(self, interaction: discord.Interaction):
        guild = interaction.guild
        channel = discord.utils.get(guild.text_channels, name=HONEYPOT_CHANNEL_NAME)

        overwrites = {
            guild.default_role: discord.PermissionOverwrite(view_channel=True, send_messages=True),
        }

        try:
            if channel is None:
                channel = await guild.create_text_channel(
                    HONEYPOT_CHANNEL_NAME, overwrites=overwrites, reason="Configuration honeypot (Saphir)"
                )
                status = f"✅ Salon créé : {channel.mention}"
            else:
                await channel.edit(overwrites=overwrites, reason="Configuration honeypot (Saphir)")
                status = f"🔄 Salon déjà présent, permissions vérifiées : {channel.mention}"
        except discord.Forbidden:
            await interaction.response.send_message("❌ Permissions insuffisantes pour créer le salon.", ephemeral=True)
            return

        already_posted = False
        async for msg in channel.history(limit=10):
            if msg.author.id == self.bot.user.id and msg.embeds and msg.embeds[0].footer.text == "Saphir · Honeypot info":
                already_posted = True
                break

        if not already_posted:
            info_embed = discord.Embed(
                title="🍯 Piège anti-bot",
                description=(
                    "Ce salon sert à repérer les **bots** et comptes automatisés qui postent partout sans distinction "
                    "sur le serveur (raids, spam).\n\n"
                    "**N'écris jamais ici, même par curiosité** — tout message posté, humain ou bot, "
                    "entraîne une expulsion immédiate du serveur."
                ),
                color=discord.Color(COLORS["gold"]),
            )
            info_embed.set_footer(text="Saphir · Honeypot info")
            try:
                await channel.send(embed=info_embed)
            except discord.HTTPException:
                pass

        embed = discord.Embed(
            title="🍯 Configuration du honeypot",
            description=(
                f"{status}\n\n"
                "N'importe quel message envoyé dans ce salon (par un humain ou un bot) "
                "entraîne la suppression du message et l'expulsion de son auteur."
            ),
            color=discord.Color(COLORS["saphir"]),
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @setup_honeypot.error
    async def setup_honeypot_error(self, interaction: discord.Interaction, error: app_commands.AppCommandError):
        if isinstance(error, app_commands.MissingPermissions):
            await interaction.response.send_message("Seul un administrateur peut utiliser cette commande.", ephemeral=True)

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.id == self.bot.user.id:
            return
        if not message.guild or message.channel.name != HONEYPOT_CHANNEL_NAME:
            return

        member = message.author
        if isinstance(member, discord.Member) and member.guild_permissions.administrator:
            return

        try:
            await message.delete()
        except discord.HTTPException:
            pass

        embed = build_honeypot_embed(member)

        try:
            await member.send(embed=embed)
        except discord.HTTPException:
            pass

        try:
            await member.kick(reason="Salon piège anti-bot (honeypot) déclenché")
        except discord.Forbidden:
            embed.description += "\n\n⚠️ Expulsion impossible (permissions ou rôle trop élevé)."

        try:
            await message.channel.send(embed=embed)
        except discord.HTTPException:
            pass


async def setup(bot):
    await bot.add_cog(Honeypot(bot))
