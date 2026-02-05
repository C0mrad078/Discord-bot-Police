
from __future__ import annotations
import os, logging
import discord
from discord.ext import commands
from dotenv import load_dotenv
from utils.config import load_config

logging.basicConfig(level=logging.INFO)

load_dotenv()
TOKEN = os.getenv("DISCORD_TOKEN")
if not TOKEN:
    raise RuntimeError("DISCORD_TOKEN não encontrado no .env")

cfg = load_config()
GUILD_ID = cfg.get("guild_id")
if not isinstance(GUILD_ID, int) or GUILD_ID == 0:
    raise RuntimeError("guild_id inválido ou não definido no config.json")

intents = discord.Intents.default()
intents.guilds = True
intents.members = True
intents.messages = True
intents.message_content = False

class HypeBot(commands.Bot):
    async def setup_hook(self):
        await self.load_extension("cogs.prisao")
        await self.load_extension("cogs.tickets")
        await self.load_extension("cogs.admin_panel")

        guild = discord.Object(id=GUILD_ID)
        # Remove comandos antigos que ficaram registrados no servidor (stale commands)
        # Ex.: quando você remove/renomeia um slash command no código, ele pode continuar
        # aparecendo no Discord e gerar "CommandNotFound" ao ser usado.
        self.tree.clear_commands(guild=guild)

        self.tree.copy_global_to(guild=guild)
        await self.tree.sync(guild=guild)

bot = HypeBot(command_prefix=cfg.get("bot", {}).get("command_prefix","!"), intents=intents)

@bot.event
async def on_ready():
    print(f"ONLINE: {bot.user} | guild={GUILD_ID}")

bot.run(TOKEN)
