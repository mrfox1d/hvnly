import disnake
from disnake.ext import commands

AUTOROLE_ID = 1529869975513468949 
BOT_ROLE_ID = 1529564768354959481

class AutoRole(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @commands.Cog.listener()
    async def on_member_join(self, member: disnake.Member):
        if member.bot:
            role = member.guild.get_role(BOT_ROLE_ID)
            if role:
                try:
                    await member.add_roles(role, reason="Автоматическая выдача роли при входе")
                except disnake.Forbidden:
                    print(f"[AutoRole] Недостаточно прав для выдачи роли {role.name} боту {member.display_name}")
                except disnake.HTTPException as e:
                    print(f"[AutoRole] Ошибка при выдаче роли: {e}")

        else:
            role = member.guild.get_role(AUTOROLE_ID)
            if role:
                try:
                    await member.add_roles(role, reason="Автоматическая выдача роли при входе")
                except disnake.Forbidden:
                    print(f"[AutoRole] Недостаточно прав для выдачи роли {role.name} пользователю {member.display_name}")
                except disnake.HTTPException as e:
                    print(f"[AutoRole] Ошибка при выдаче роли: {e}")

def setup(bot: commands.Bot):
    bot.add_cog(AutoRole(bot))