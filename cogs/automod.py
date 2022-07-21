import discord
from discord.ext import commands, pages

from utils.views import DropdownView, EmojiView, QueueView
from utils.converters import ValidAction, ValidMethod
from cogs.events import events
from utils import database

from typing import Optional

async def queue_paginator(client: commands.Bot, queue: list):
    """Generates the quarantine queue."""
    # fetch users using each id in the queue
    user_list = [await client.fetch_user(user_id) for user_id in queue]
    
    # split list every 10 users (separate pages)
    ul_sep = [user_list[i:i + 10] for i in range(0, len(user_list), 10)]

    embeds = []

    # create page embeds using lists
    for index, list in enumerate(ul_sep):
        embed = discord.Embed(
            title = f"Queue ({len(user_list)} total)",
            color = 0x2f3136
        )

        # render user and their place in queue
        embed.description = '\n'.join([f'`{i + 1}.` {user}' for i, user in enumerate(list)])
        embed.set_footer(text = f"page {index + 1} out of {len(ul_sep)}")
        embeds.append(embed)
    
    return pages.Paginator(embeds, show_disabled = False, show_indicator = False)

async def e_or_s_list(ctx, msg, kind, cache = None):
    """Generates the emoji/sticker cache."""
    if cache is None:
        # get cache list from database
        db = database.Guild(ctx.guild)
        guild = db.get()
        
        cache = guild.emoji_cache if kind == 'emoji' else guild.sticker_cache
    
    # use "add one" / "add all" buttons in message
    view = EmojiView(msg, ctx, cache, kind)

    embed = discord.Embed(color = 0x2f3136)

    if not cache:
        embed.description = f"No {kind}s are in the cache at the moment."
        return embed, None

    str_list = []

    # list emojis/stickers and their cdn links
    for entry in cache:
        name = entry[1]
        url = f"https://cdn.discordapp.com/" + (f"emojis/{entry[0]}" if kind == 'emoji' else f"stickers/{entry[0]}.png")

        str_list.append(f"**[{name}]({url})**")

    embed.description = f"**Cached {kind}s:** " + ", ".join(str_list)

    return embed, view

class automod(commands.Cog):
    def __init__(self, client):
        self.client = client

    async def cog_check(self, ctx):
        # disables commands until the user sets up the bot
        if not database.Guild(ctx.guild).exists() and ctx.author.guild_permissions.administrator:
            await ctx.send("**Error:** set up the bot with `t!setup` first")
            return False
        else:
            return True

    @commands.command(aliases = ["t"])
    @commands.has_permissions(manage_roles = True, kick_members = True, ban_members = True)
    @commands.bot_has_permissions(manage_roles = True, kick_members = True, ban_members = True)
    async def toggle(self, ctx: commands.Context, method: Optional[ValidMethod]):
        user_choice = None

        embed = discord.Embed()
        embed.set_author(name = ctx.message.author.name, icon_url = ctx.message.author.display_avatar)

        # let the user choose via dropdown if a method isn't given
        if not method:
            embed.description = "Select the method to use for dealing with new accounts using the dropdown menu below."
            embed.color = self.client.gray

            view = DropdownView("method", ctx)
            user_choice = await ctx.send(embed = embed, view = view)

            # get selection from dropdown
            await view.wait()
            method = view.value

        database.Guild(ctx.guild).set_field('method', method)
        
        embed.description = f"Set the method to **{method.capitalize()}**."
        embed.color = discord.Color.brand_green()

        if user_choice:
            # edit the dropdown message
            await user_choice.edit(embed = embed, view = None)
        else:
            await ctx.send(embed = embed)
    
    @commands.command(aliases = ["q"])
    @commands.has_permissions(manage_roles = True, kick_members = True, ban_members = True)
    @commands.bot_has_permissions(manage_roles = True, kick_members = True, ban_members = True)
    async def quarantine(self, ctx: commands.Context, members: commands.Greedy[discord.Member], action: Optional[ValidAction]):
        db = database.Guild(ctx.guild)
        guild = db.get()

        # get quarantine role and users to manage 
        # (will be everyone with the quarantine role if no members are given)
        q_role = ctx.message.guild.get_role(guild.q_role_id)
        quarantine = members if members else q_role.members

        embed = discord.Embed()
        embed.color = self.client.gray

        if not quarantine:
            embed.description = "Nobody's in quarantine right now."
            return await ctx.send(embed = embed)

        # if nothing was given, display information about the server's quarantine
        if not members and not action:
            quarantine = q_role.members
            latest_user = quarantine[0]

            embed.set_author(name = ctx.message.guild.name)
            embed.add_field(name = "Users in quarantine:", value = f"{len(quarantine)}")
            embed.add_field(name = "Latest user:", value = f"{latest_user}")
            embed.add_field(name = "Commands", value = "`t!q clear` - removes the quarantine role\n`t!q kick|ban` - kicks/bans users from the server\n`t!q add` - adds users to quarantines", inline = False)
            embed.set_thumbnail(url = latest_user.display_avatar)

            embed.set_footer(text = "(commands will apply to everyone in quarantine if nobody is specified)")

            # add a 'queue' button if there are people in it
            view = QueueView(guild) if guild.queue else None

            return await ctx.send(embed = embed, view = view)
        
        # all of the for statements are separated in case it helps performance, not too sure though

        if action == "clear":
            for member in quarantine:
                await member.remove_roles(q_role)

            action_taken = "Cleared"
        
        elif action == "kick":
            for member in quarantine:
                await member.kick()

            action_taken = "Kicked"
        
        elif action == "ban":
            for member in quarantine:
                await member.ban()

            action_taken = "Banned"

        elif not action or action == "add":
            log = await self.client.fetch_channel(guild.log_id)
            
            for member in quarantine:
                if str(member.id) in guild.quarantine or member.id in guild.queue:
                    if len(quarantine) == 1:
                        # send an error if the one member that was listed is being quarantined already
                        return await ctx.send("**Error:** that user is already quarantined!")
                    
                    # continue in case there are others listed that have not been quarantined yet
                    continue
                
                position = await events(self.client).quarantine(member)

                # log the quarantine
                log_embed = events(self.client).create_log_embed(
                    title = "Quarantined Member", 
                    member = member,
                    reason = f"Manually added by {ctx.message.author.mention}",
                    extra = position
                )

                await log.send(embed = log_embed)

            action_taken = "Quarantined"

        elif action == "queue":
            if not guild.queue:
                embed.description = "The queue is currently empty."
                return await ctx.send(embed = embed)

            # get a list members in the queue
            paginator = await queue_paginator(self.client, guild.queue)
            return await paginator.send(ctx)

        embed.description = f"**{action_taken} {len(quarantine)} member(s):**"
        
        # send confirmation embed differently depending on how many members were managed
        if len(quarantine) > 20:
            embed.description = f"**{action_taken} {len(quarantine)} member(s):**"
        elif len(quarantine) > 1:
            embed.description = f"**{action_taken}:\n{', '.join([u.mention for u in quarantine])}**"
        else:
            embed.description = f"**{action_taken} {quarantine[0].mention}.**"

        embed.color = discord.Color.brand_green()
        
        await ctx.send(embed = embed)

    @commands.command(aliases = ["p"])
    @commands.has_permissions(administrator = True)
    async def priority(self, ctx: commands.Context, channels: commands.Greedy[discord.TextChannel]):
        db = database.Guild(ctx.guild)
        guild = db.get()

        added = []
        removed = []

        embed = discord.Embed(color = self.client.gray)

        if not channels:
            # list all prioritized channels if no channels are given
            if not guild.priority:
                embed.description = "No channels are being prioritized right now."
                embed.set_footer(text = "Add/remove channels by listing them after t!priority")
            else:
                embed.description = "**Prioritized channels:**\n" + ', '.join([f'<#{c}>' for c in guild.priority])
                embed.set_footer(text = f"{len(guild.priority)} total")
        else:
            for channel in channels:
                # add or remove channels depending on if they're in the priority list
                if channel.id not in guild.priority:
                    db.push_to_list('priority', channel.id)
                    added.append(channel.id)
                else:
                    db.pull_from_list('priority', channel.id)
                    removed.append(channel.id)

            if added:
                embed.add_field(name = 'Added:', value = ', '.join([f'<#{c}>' for c in added]))
            
            if removed:
                embed.add_field(name = 'Removed:', value = ', '.join([f'<#{c}>' for c in removed]))

        await ctx.send(embed = embed)

    @commands.command(aliases = ["a"])
    @commands.has_permissions(administrator = True)
    async def allow(self, ctx: commands.Context, roles: commands.Greedy[discord.Role]):
        db = database.Guild(ctx.guild)
        guild = db.get()

        added = []
        removed = []

        embed = discord.Embed(color = self.client.gray)

        if not roles:
            # list allowed roles
            if not guild.allowed:
                embed.description = "No roles have been allowed yet."
                embed.set_footer(text = "Add/remove roles by listing them after t!allow")
            else:
                embed.description = "**Allowed roles:**\n" + ', '.join([f'<@&{r}>' for r in guild.allowed])
                embed.set_footer(text = f"{len(guild.allowed)} total")
        else:
            for role in roles:
                # add or remove channels depending on if they're in the priority list
                if not guild.allowed or role.id not in guild.allowed:
                    db.push_to_list('allowed', role.id)
                    added.append(role.id)
                else:
                    db.pull_from_list('allowed', role.id)
                    removed.append(role.id)

            if added:
                embed.add_field(name = 'Added:', value = ', '.join([f'<@&{r}>' for r in added]))
            
            if removed:
                embed.add_field(name = 'Removed:', value = ', '.join([f'<@&{r}>' for r in removed]))

        await ctx.send(embed = embed)

    @commands.command(aliases = ["emojis", "e"])
    @commands.has_permissions(manage_emojis = True)
    @commands.bot_has_permissions(manage_emojis = True)
    async def emoji(self, ctx: commands.Context):
        # it might take some time to load emojis
        loading = discord.Embed(
            description = "Loading...",
            color = self.client.gray
        )

        # gets an embed containing the cache (and a view, if the cache is not empty)
        msg = await ctx.send(embed = loading)
        embed, view = await e_or_s_list(ctx, msg, 'emoji')
        await msg.edit(embed = embed, view = view)

    @commands.command(aliases = ["stickers", "s"])
    @commands.has_permissions(manage_emojis_and_stickers = True)
    @commands.bot_has_permissions(manage_emojis_and_stickers = True)
    async def sticker(self, ctx: commands.Context):
        # same as emoji but for stickers
        loading = discord.Embed(
            description = "Loading...",
            color = self.client.gray
        )

        msg = await ctx.send(embed = loading)
        embed, view = await e_or_s_list(ctx, msg, 'sticker')
        await msg.edit(embed = embed, view = view)

    @commands.command(aliases = ["lock", "l"])
    @commands.has_permissions(manage_roles = True, kick_members = True, ban_members = True)
    async def lockdown(self, ctx: commands.Context):
        db = database.Guild(ctx.guild)
        guild = db.get()

        embed = discord.Embed(color = self.client.gray)

        # toggle lockdown
        new_status = not guild.lockdown
        db.set_field('lockdown', new_status)

        status = "enabled" if new_status else "disabled"
        embed.description = f"Lockdown has been {status}!"

        await ctx.send(embed = embed)

def setup(bot):
    bot.add_cog(automod(bot))