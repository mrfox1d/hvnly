import disnake
from disnake.ext import commands
from disnake import Status, ActivityType, Activity, Intents
import os
from dotenv import load_dotenv
from database import init_db

load_dotenv()

tk = os.getenv("TOKEN")

bot = commands.Bot(command_prefix=".", intents=Intents.all(),
                   help_command=None, status=Status.dnd,
                   activity=Activity(name="🌐 website: shitcode.pw"))

@bot.event
async def on_ready():
    init_db()
    print(f"Logged in as {bot.user}")

bot.load_extensions("cogs")

bot.run(tk)