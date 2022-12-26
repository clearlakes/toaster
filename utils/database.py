import discord

import motor.motor_asyncio

from configparser import ConfigParser
from typing import Union

config = ConfigParser()
config.read("config.ini")

# connect to database
_mongo_uri = str(config.get("mongo", "uri"))
_mongo_db_name = str(config.get("mongo", "database"))
_mongo_coll_name = str(config.get("mongo", "collection"))

_mongo_client = motor.motor_asyncio.AsyncIOMotorClient(_mongo_uri)
_db = _mongo_client[_mongo_db_name][_mongo_coll_name]

class Document:
    def __init__(self, document: dict):
        if document:
            # list of variables used throughout the bot
            # this can probably be done in automatically but this gives type hints
            get = lambda key: document.get(key)

            self.queue: list = get('queue')
            self.method: str = get('method')
            self.log_id: int = get('log_id')
            self.wait_id: int = get('wait_id')
            self.actions: int = get('actions')
            self.min_age: int = get('min_age')
            self.history: int = get('history')
            self.allowed: list = get('allowed')
            self.priority: list = get('priority')
            self.lockdown: bool = get('lockdown')
            self.q_role_id: int = get('q_role_id')
            self.quarantine: dict = get('quarantine')
            self.role_cache: list = get('role_cache')
            self.emoji_cache: list = get('emoji_cache')
            self.sticker_cache: list = get('sticker_cache')
            self.channel_cache: list = get('channel_cache')
            self.strike_topics: dict = get('strike_topics')
            self.watching_roles: bool = get('watch_roles')
            self.watching_emojis: bool = get('watch_emojis')
            self.watching_channels: bool = get('watch_channels')

class Guild:
    def __init__(self, guild: discord.Guild):
        self.guild = {'guild_id': guild.id}
        self.guild_id = guild.id

    async def exists(self) -> bool:
        """Checks if a guild exists in the database."""
        return await _db.count_documents(self.guild, limit = 1)

    async def delete(self) -> None:
        """Deletes a guild from the database."""
        await _db.delete_one(self.guild)

    async def increment(self, amount: int = 1) -> None:
        """Increases the total number of 'actions' by the amount specified."""
        await _db.update_one(self.guild, {'$inc': {'actions': amount}})

    async def push_to_list(self, field: str, value) -> None:
        """Pushes a value to the given field."""
        await _db.update_one(self.guild, {'$push': {field: {'$each': [value]}}})

    async def pull_from_list(self, field: str, value) -> None:
        """Pulls (removes) a value from a given field."""
        await _db.update_one(self.guild, {'$pull': {field: value}})

    async def clear_list(self, field: str) -> None:
        """Clears the given field's list."""
        await _db.update_one(self.guild, {'$set': {field: []}})

    async def set_field(self, field: str, value) -> None:
        """Creates/sets the specified field to a given value."""
        await _db.update_one(self.guild, {'$set': {field: value}})

    async def del_field(self, field: str) -> None:
        """Removes the specified field."""
        await _db.update_one(self.guild, {'$unset': {field: 1}})

    async def get(self) -> Union[Document, None]:
        """Returns the guild's database entry as a class."""
        _doc = await _db.find_one(self.guild)

        return Document(_doc) if _doc else None

    async def add_guild(
        self,
        method: str,
        log_id: int,
        min_age: int,
        watch_channels: bool,
        watch_emojis: bool,
        watch_roles: bool,
        q_role: int,
        wait_id: int,
        history: int
    ) -> None:
        """Adds a guild to the database using the ids given in setup."""
        await _db.insert_one({
            'guild_id': self.guild_id,
            'actions': 0,
            'log_id': log_id,
            'wait_id': wait_id,
            'history': history,
            'q_role_id': q_role,
            'method': method.lower(),
            'min_age': min_age,
            'watch_channels': watch_channels,
            'watch_emojis': watch_emojis,
            'watch_roles': watch_roles,
            'lockdown': False,
            'quarantine': {},
            'queue': [],
            'role_cache': [],
            'emoji_cache': [],
            'sticker_cache': [],
            'channel_cache': [],
            'allowed': [],
            'priority': []
        })
