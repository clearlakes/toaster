import discord
from discord.ext import commands
from datetime import datetime
import configparser

# get the current time (used for getting uptime later on)
start_time = datetime.now()

# read the config file for the token
config = configparser.ConfigParser()
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
    for cog in ["automod", "events", "main"]:
        client.load_extension(f"cogs.{cog}")

    print("toaster ready")

# start the bot
client.run(token)