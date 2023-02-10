import discord
from discord.ext import commands

from bot import Toaster

from datetime import datetime
from typing import Any

class BaseEmbed(discord.Embed):
    def __init__(self, *,
        color: int | discord.Colour | None = 0x2F3136,
        title: Any | None = None,
        url: Any | None = None,
        description: Any | None = None,
        timestamp: datetime | None = None,
    ):

        super().__init__(
            color = color,
            title = title,
            url = url,
            description = description,
            timestamp = timestamp
        )

class BaseCog(commands.Cog):
    def __init__(self, client: Toaster):
        self.client = client

class BaseGroupCog(commands.GroupCog):
    def __init__(self, client: Toaster):
        self.client = client
        super().__init__()