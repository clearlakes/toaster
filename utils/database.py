from __future__ import annotations

import discord
import pymongo
import configparser
from typing import Union

config = configparser.ConfigParser()
config.read("config.ini")

# connect to database
_db_url = str(config.get("server", "mongodb"))
_mongo = pymongo.MongoClient(_db_url)
_db = _mongo.toaster.v2

class Document:
    def __init__(self, document: dict):
        if document:
            # list of variables used throughout the bot
            # this can probably be done in automatically but this allows for intellisense
            self.queue: list = document['queue']
            self.method: str = document['method']
            self.log_id: int = document['log_id']
            self.wait_id: int = document['wait_id']
            self.actions: int = document['actions']
            self.min_age: int = document['min_age']
            self.history: int = document['history']
            self.priority: list = document['priority']
            self.q_role_id: int = document['q_role_id']
            self.quarantine: dict = document['quarantine']
            self.role_cache: list = document['role_cache']
            self.emoji_cache: list = document['emoji_cache']
            self.sticker_cache:list = document['sticker_cache']
            self.channel_cache:list = document['channel_cache']
            self.watching_roles: bool = document['watch_roles']
            self.watching_emojis: bool = document['watch_emojis']
            self.watching_channels: bool = document['watch_channels']

class Guild:
    def __init__(self, guild: discord.Guild):
        self.guild = {'guild_id': guild.id}
        self.guild_id = guild.id

    def exists(self) -> bool:
        """Checks if a guild exists in the database."""
        return _db.count_documents(self.guild, limit = 1)

    def delete(self) -> None:
        """Deletes a guild from the database."""
        return _db.delete_one(self.guild)

    def increment(self, amount: int = 1) -> None:
        """Increases the total number of 'actions' by the amount specified."""
        _db.update_one(self.guild, {'$inc': {'actions': amount}})

    def add_quarantine(self, user_id: int, channel_id: int) -> None:
        """Adds a user-channel pair entry to the list of active quarantines."""
        _db.update_one(self.guild, {'$set': {f'quarantine.{user_id}': channel_id}})

    def del_quarantine(self, user_id: int) -> None:
        """Removes the user from either the list of quarantines or the queue."""
        _db.update_one(self.guild, {'$unset': {f'quarantine.{user_id}': 1}})
        _db.update_one(self.guild, {'$pull': {'queue': user_id}})

    def push_to_list(self, field: str, obj, pre: bool = False) -> None:
        """Pushes an object to the given field."""
        _db.update_one(self.guild, {'$push': {field: {'$each': [obj]}}})

    def pull_from_list(self, field: str, obj) -> None:
        """Pulls (removes) an object from a given field."""
        _db.update_one(self.guild, {'$pull': {field: obj}})
    
    def clear_list(self, field: str) -> None:
        """Clears the given field's list."""
        _db.update_one(self.guild, {'$set': {field: []}})

    def set_method(self, method: str) -> None:
        """Sets the method of dealing with new accounts for the guild."""
        _db.update_one(self.guild, {'$set': {'method': method.lower()}}, upsert = True)

    def get(self) -> Union[Document, None]:
        """Returns the guild's database entry as a class."""
        _doc = _db.find_one(self.guild)
        
        return Document(_doc) if _doc else None

    def add_guild(self, method: str, log_id: int, min_age: int, watch_channels: bool, watch_emojis: bool, watch_roles: bool, q_role: int, wait_id: int, history: int) -> None:
        """Adds a guild to the database using the ids given in setup."""
        _db.insert_one({
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
            'quarantine': {},
            'queue': [],
            'role_cache': [],
            'emoji_cache': [],
            'sticker_cache': [],
            'channel_cache': [],
            'priority': []
        })
