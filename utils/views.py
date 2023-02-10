import discord
from discord.ext import commands

from utils.base import BaseEmbed
from utils import database
from cogs import automod

import aiohttp
import io

async def refresh(view: discord.ui.View, kind, original, removed, orig_msg: discord.Message, ctx: commands.Context):
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
    await db.pull_from_list(f'{kind}_cache', {'$in': chosen_list})

    return created

class HelpView(discord.ui.View):
    def __init__(self, ctx: commands.Context, msg: discord.Message = None):
        super().__init__(timeout = None)
        self.ctx = ctx
        self.msg = msg

        self.children[0].label = "commands"

    async def interaction_check(self, interaction: discord.Interaction):
        return interaction.user == self.ctx.author

    @property
    def get_embed_and_view(self):
        page_to_switch_to = self.children[0].label
        embed = BaseEmbed(title = "Help - ")

        if page_to_switch_to == "commands":
            embed.title += "Commands"
            embed.description = """
            `t!info                ` - lists information about the bot
            `t!setup               ` - sets up the quarantine functionality of the bot
            `t!allow *[roles]      ` - allows specified roles to view quarantines
            `t!toggle *[method]    ` - changes the mode of the bot
            `t!lockdown            ` - applies the current method to anyone joining
            `t!priority *[channels]` - distinguishes important channels
            `t!quarantine | t!q    ` - shows information about current quarantines
            `t!q *[users]          ` - adds users to quarantine
            `  ^^^ + clear/kick/ban` - manages users in quarantine (+)
            ` t!sticker ` | ` t!emoji ` - displays recently deleted emojis/stickers
            """
            embed.set_footer(text = '*: arguments are optional\n+: applies to everyone in quarantine if nobody is specified')
            self.children[0].label = "permissions"
        else:
            embed.title += "Permissions"
            embed.description = """
            **Required permissions (user):**
            `t!info            ` - none
            `t!setup           ` - administrator
            `t!allow           ` - administrator
            `t!toggle          ` - manage roles, kick/ban
            `t!lockdown        ` - manage roles, kick/ban
            `t!priority        ` - administrator
            `t!quarantine      ` - manage roles, kick/ban
            `t!sticker` | `t!emoji` - manage emojis/stickers

            **Required permissions (bot):**
            manage emojis/roles/channels, kick/ban, view audit log, read message history
            """
            self.children[0].label = "commands"

        return embed, self

    @discord.ui.button()
    async def switch(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer()
        embed, view = self.get_embed_and_view
        await self.msg.edit(embed = embed, view = view)

class EmojiView(discord.ui.View):
    def __init__(self, msg, ctx, given_list, kind):
        super().__init__()
        self.list = given_list
        self.kind = kind
        self.ctx = ctx
        self.msg = msg

    @discord.ui.button(label = "add one", style = discord.ButtonStyle.gray)
    async def add_one(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user != self.ctx.author:
            return

        db = database.Guild(interaction.guild)

        # brings up a selection for the user to choose
        view = SelectEmojiView(self.kind, db, self.list, self.ctx, self.msg, self, interaction)
        await interaction.response.send_message(view = view, ephemeral = True)

    @discord.ui.button(label = "add all", style = discord.ButtonStyle.gray)
    async def add_all(self, interaction: discord.Interaction, button: discord.ui.Button):
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
    def __init__(self, user: discord.Member, options: dict = {"yes": True, "no i don't care": False}):
        super().__init__()
        self.value = None
        self.user_id = user.id

        async def callback(interaction: discord.Interaction):
            self.value = options[interaction.data["custom_id"].split(":")[-1]]
            self.stop()

        for label in options.keys():
            btn = discord.ui.Button(label = label, custom_id = f"cv:{label}")
            btn.callback = callback
            self.add_item(btn)

    async def interaction_check(self, interaction: discord.Interaction):
        return self.user_id == interaction.user.id

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
    async def callback(self, interaction: discord.Interaction, select: discord.ui.Select):
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

class Paginator(discord.ui.View):
    def __init__(self, title: str, content: list[str], generate: bool = False):
        super().__init__(timeout = None)

        if generate:
            for num, item in enumerate(content):
                content[num] = f"**{num + 1}.** {item}"

        sep_list = [content[i:i + 10] for i in range(0, len(content), 10)]
        self.pages = [BaseEmbed(description = "\n".join(l)).set_author(name = title) for l in sep_list]
        self.current = 0

        self.update_btns()

    def update_btns(self):
        self.children[0].disabled = self.current == 0
        self.children[1].label = f"{self.current + 1}/{len(self.pages)}"
        self.children[2].disabled = (self.current + 1) == len(self.pages)

    async def update_page(self, interaction: discord.Interaction, next: bool = True):
        self.current = self.current + 1 if next else self.current - 1
        self.update_btns()

        await interaction.response.edit_message(embed = self.pages[self.current], view = self)

    @discord.ui.button(label = "<", custom_id = "pg:back", disabled = True)
    async def back(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.update_page(interaction, False)

    @discord.ui.button(label = "-/-", custom_id = "pg:num", disabled = True)
    async def page_num(self, interaction: discord.Interaction, button: discord.ui.Button):
        return

    @discord.ui.button(label = ">", custom_id = "pg:next")
    async def next(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.update_page(interaction, True)