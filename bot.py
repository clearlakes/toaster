import discord
from discord.ext import commands

from configparser import ConfigParser
from datetime import datetime
import aiohttp
import logging

class Toaster(commands.Bot):
    def __init__(self):
        super().__init__(
            help_command = None,
            command_prefix = commands.when_mentioned_or("t!"),
            intents = discord.Intents.all()
        )

        self.log = logging.getLogger("discord")
        self.log.name = ""

        config = ConfigParser()
        config.read("config.ini")

        self.init_time = datetime.now()
        self.token = str(config.get("bot", "token"))

    async def setup_hook(self):
        self.session = aiohttp.ClientSession(loop = self.loop)

        for cog in ["automod", "custom", "events", "main", "vc"]:
            await self.load_extension(f"cogs.{cog}")

    async def on_ready(self):
        self.log.info("toaster ready")

    async def close(self):
        await self.session.close()

    def run(self):
        super().run(self.token, reconnect = True)

if __name__ == '__main__':
    toaster = Toaster()
    toaster.run()