
import discord

def is_admin_member(member: discord.Member, admin_role_ids: list[int]) -> bool:
    if member.guild_permissions.administrator:
        return True
    return any(role.id in admin_role_ids for role in member.roles)

def admin_only(admin_role_ids: list[int]):
    async def predicate(interaction: discord.Interaction) -> bool:
        if not interaction.guild or not isinstance(interaction.user, discord.Member):
            return False
        return is_admin_member(interaction.user, admin_role_ids)
    return discord.app_commands.check(predicate)
