import discord
from discord.ext import commands

from configparser import ConfigParser
from datetime import datetime

# get the current time (used for getting uptime later on)
start_time = datetime.now()

# read the config file for the token
config = ConfigParser()
config.read("config.ini")

token = str(config.get("server", "token"))

# get discord intents and command prefix to use
intents = discord.Intents.all()
client = commands.Bot(command_prefix=commands.when_mentioned_or("t!"), intents=intents)

# remove default help command
client.remove_command('help')

client.initialized_at = start_time
client.gray = 0x2f3136

@client.event
async def on_ready():    
    # load cogs
    for cog in ["automod", "custom", "events", "main"]:
        client.load_extension(f"cogs.{cog}", store = False)

    await client.sync_commands()

    print("toaster ready")

# start the bot
client.run(token)