import discord
from discord.ext import commands

from config import VOICE_ROLE_NAME


class VoiceRole(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.Cog.listener()
    async def on_voice_state_update(
        self, member: discord.Member, before: discord.VoiceState, after: discord.VoiceState
    ):
        if before.channel == after.channel:
            return

        role = discord.utils.get(member.guild.roles, name=VOICE_ROLE_NAME)
        if role is None:
            return

        try:
            if after.channel and not before.channel:
                await member.add_roles(role, reason="Connecté à un salon vocal")
            elif before.channel and not after.channel:
                await member.remove_roles(role, reason="Déconnecté des salons vocaux")
        except discord.Forbidden:
            pass


async def setup(bot):
    await bot.add_cog(VoiceRole(bot))
