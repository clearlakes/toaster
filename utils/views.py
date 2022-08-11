import discord
from discord.ext import commands

from utils import database
from cogs import automod

import aiohttp
import io

async def refresh(view: discord.ui.View, kind, original, removed, orig_msg, ctx):
    """Refreshes the list of emojis/stickers in a message."""
    # use a list of all the emojis/stickers that weren't deleted as the new cache
    new_cache = [item for item in original if item not in removed]
    embed, view = await automod.e_or_s_list(ctx, orig_msg, kind, new_cache)

    await orig_msg.edit(embed = embed, view = view)

async def create(kind, interaction: discord.Interaction, db: database.Guild, chosen_list):
    """Uploads cached emojis/stickers."""
    
    async def to_bytes(id):
        """Converts the url of an emoji/sticker into bytes."""
        url = 'https://cdn.discordapp.com/' + (f'emojis/{id}' if kind == 'emoji' else f'stickers/{id}.png')
        
        # return the image in bytes
        async with aiohttp.ClientSession() as aio:
            async with aio.get(url) as res:
                return await res.read()

    created = []
    
    if kind == 'emoji':
        for emoji in chosen_list:
            created.append(await interaction.guild.create_custom_emoji(name = emoji[1], image = await to_bytes(emoji[0])))
    
    elif kind == 'sticker': 
        for sticker in chosen_list:
            file = discord.File(io.BytesIO(await to_bytes(sticker[0]), f'{sticker[1]}.png'))
            created.append(await interaction.guild.create_sticker(name = sticker[1], file = file))
    
    # remove all added emojis from cache
    db.pull_from_list(f'{kind}_cache', {'$in': chosen_list})

    return created

class EmojiView(discord.ui.View):
    def __init__(self, msg, ctx, given_list, kind):
        super().__init__()
        self.list = given_list
        self.kind = kind
        self.ctx = ctx
        self.msg = msg

    @discord.ui.button(label = "add one", style = discord.ButtonStyle.gray)
    async def add_one(self, button: discord.ui.Button, interaction: discord.Interaction):
        if interaction.user != self.ctx.author:
            return
        
        db = database.Guild(interaction.guild)

        # brings up a selection for the user to choose
        view = SelectEmojiView(self.kind, db, self.list, self.ctx, self.msg, self, interaction)
        await interaction.response.send_message(view = view, ephemeral = True)

    @discord.ui.button(label = "add all", style = discord.ButtonStyle.gray)
    async def add_all(self, button: discord.ui.Button, interaction: discord.Interaction):
        if interaction.user != self.ctx.author:
            return

        db = database.Guild(interaction.guild)

        # uploads every cached emoji (self.list is the cache list)
        await create(self.kind, interaction, db, self.list)

        embed = discord.Embed(color = discord.Color.brand_green())
        embed.set_author(name = f'Added {len(self.list)} {self.kind}(s)', icon_url = interaction.user.display_avatar)

        await interaction.response.send_message(embed = embed)
        await refresh(self, self.kind, self.list, self.list, self.msg, self.ctx)

class SelectEmojiView(discord.ui.View):
    def __init__(self, kind, db, given_list, ctx, msg, orig_view, interaction):
        # pass literally everything from emojiview into this view
        self.db = db
        self.ctx = ctx
        self.msg = msg
        self.kind = kind
        self.list = given_list
        self.orig_view = orig_view
        self.orig_inter: discord.Interaction = interaction

        super().__init__()

        # generate emoji choices and set their values to "id:name" (values can't be lists)
        self.children[0].options = [discord.SelectOption(label = item[1], value = f"{item[0]}:{item[1]}") for item in given_list]

    @discord.ui.select(placeholder = "Select the one you want to re-add")
    async def callback(self, select: discord.ui.Select, interaction: discord.Interaction):
        #turn string value back into [id, name]
        emoji = select.values[0].split(':')
        emoji[0] = int(emoji[0])
        
        # upload chosen emoji
        e_or_s = await create(self.kind, interaction, self.db, [emoji])

        # use colons around the name if it's an emoji
        if isinstance(e_or_s[0], discord.Emoji):
            result = f':{e_or_s[0].name}:'
        else:
            result = e_or_s[0].name

        embed = discord.Embed(color = discord.Color.brand_green())
        embed.set_author(name = f'Added {result}', icon_url = interaction.user.display_avatar)

        await self.orig_inter.followup.send(embed = embed)
        await refresh(self.orig_view, self.kind, self.list, [emoji], self.msg, self.ctx)

class ConfirmView(discord.ui.View):
    def __init__(self, ctx):
        super().__init__()
        self.value = None
        self.ctx = ctx

    @discord.ui.button(label = "yes", style = discord.ButtonStyle.primary)
    async def confirm(self, button: discord.ui.Button, interaction: discord.Interaction):
        if interaction.user != self.ctx.author:
            return

        self.value = True   # chose yes
        self.stop()

    @discord.ui.button(label = "i don't care", style = discord.ButtonStyle.secondary)
    async def cancel(self, button: discord.ui.Button, interaction: discord.Interaction):
        if interaction.user != self.ctx.author:
            return

        self.value = False  # chose no
        self.stop()

class DropdownView(discord.ui.View):
    def __init__(self, kind, ctx: commands.Context):
        self.value = None
        self.kind = kind
        self.ctx = ctx

        # this is used in setup in case the user wants to have the bot create channels/roles
        options = [
            discord.SelectOption(
                label = f"[make the {kind} for me]",
                value = "0"
            )
        ]

        if kind == "role":
            # loop over every role except for @everyone
            for role in ctx.message.guild.roles[1:]:
                # if the role is above the client's own role, do not add it
                if role > self.ctx.message.guild.self_role:
                    continue

                choice = discord.SelectOption(
                    label = role.name,
                    value = str(role.id)
                )
                options.append(choice)

        if kind == "channel":
            # loop over every visible channel
            for index, channel in enumerate(reversed(ctx.message.guild.text_channels)):
                if index == 24:
                    break

                choice = discord.SelectOption(
                    label = channel.name,
                    value = str(channel.id)
                )
                options.append(choice)
        
        elif kind == "method":
            # dropdown options
            options = [
                discord.SelectOption(
                    label = "Ignore",
                    description = "ignore new accounts"
                ),
                discord.SelectOption(
                    label = "Quarantine",
                    description = "lock new accounts in private channels"
                ),
                discord.SelectOption(
                    label = "Kick",
                    description = "kick new accounts from the server"
                ),
                discord.SelectOption(
                    label = "Ban",
                    description = "permanently ban new accounts from the server"
                )
            ]

        elif kind == "length of time":
            # values are in seconds
            options = [
                discord.SelectOption(
                    label = "3 days",
                    value = "259200"
                ),
                discord.SelectOption(
                    label = "1 week",
                    value = "604800"
                ),
                discord.SelectOption(
                    label = "2 weeks",
                    value = "1209600"
                ),
                discord.SelectOption(
                    label = "1 month",
                    value = "2630000"
                )
            ]

        super().__init__()
        self.children[0].options = options
        self.children[0].placeholder = f"Select a {kind}"
    
    @discord.ui.select()
    async def callback(self, select: discord.ui.Select, interaction: discord.Interaction):
        if interaction.user != self.ctx.author:
            return

        self.value = select.values[0]

        if self.value.isnumeric():
            self.value = int(self.value)

        # if the user chose to have the bot make a channel for them (most likely log channel)
        if self.value == 0:
            # make the log channel private (disable reading for regular users)
            overwrites = {
                self.ctx.message.guild.default_role: discord.PermissionOverwrite(view_channel = False),
                self.ctx.message.guild.self_role: discord.PermissionOverwrite(view_channel = True)}

            # create the channel using the permission overwrite
            log_channel = await self.ctx.message.guild.create_text_channel("toaster-logs", overwrites=overwrites)
            self.value = log_channel.id

        select.disabled = True
        self.stop()

class QueueView(discord.ui.View):
    def __init__(self, db_doc: database.Document):
        super().__init__()
        self.db = db_doc

    @discord.ui.button(label = "queue", style = discord.ButtonStyle.gray)
    async def callback(self, button: discord.ui.Button, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral = True)
        
        # create the queue list
        paginator = await automod.queue_paginator(interaction.client, self.db.queue)
        
        # pass if a NotFound error appears (everything works even if it does)
        try:
            await paginator.respond(interaction, ephemeral = True)
        except discord.NotFound:
            pass