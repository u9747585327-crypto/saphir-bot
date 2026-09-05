import discord
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
