import discord
from discord.ext import commands

from utils.base import BaseCog, BaseEmbed

from utils.views import DropdownView, EmojiView, Paginator
from utils.converters import ValidAction, ValidMethod
from cogs.events import Events
from utils import database

from typing import Optional

async def e_or_s_list(ctx, msg, kind, cache = None):
    """Generates the emoji/sticker cache."""
    if cache is None:
        # get cache list from database
        db = database.Guild(ctx.guild)
        guild = await db.get()

        cache = guild.emoji_cache if kind == 'emoji' else guild.sticker_cache

    # use "add one" / "add all" buttons in message
    view = EmojiView(msg, ctx, cache, kind)

    embed = BaseEmbed()

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

class Automod(BaseCog):
    async def cog_check(self, ctx):
        exists = await database.Guild(ctx.guild).exists()

        # disables commands until the user sets up the bot
        if not exists:
            if ctx.author.guild_permissions.administrator:
                await ctx.send("**Error:** set up the bot with `t!setup` first")

            return False
        else:
            return True

    @commands.command(aliases = ["t"])
    @commands.has_permissions(manage_roles = True, kick_members = True, ban_members = True)
    @commands.bot_has_permissions(manage_roles = True, kick_members = True, ban_members = True)
    async def toggle(self, ctx: commands.Context, method: Optional[ValidMethod]):
        user_choice = None

        embed = BaseEmbed()
        embed.set_author(name = ctx.message.author.name, icon_url = ctx.message.author.display_avatar)

        # let the user choose via dropdown if a method isn't given
        if not method:
            embed.description = "Select the method to use for dealing with new accounts using the dropdown menu below."

            view = DropdownView("method", ctx)
            user_choice = await ctx.send(embed = embed, view = view)

            # get selection from dropdown
            await view.wait()
            method = view.value

        await database.Guild(ctx.guild).set_field('method', method.lower())

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
        guild = await db.get()

        # get quarantine role and users to manage
        # (will be everyone with the quarantine role if no members are given)
        q_role = ctx.message.guild.get_role(guild.q_role_id)
        quarantine = members if members else q_role.members if q_role else None

        embed = BaseEmbed()

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

            return await ctx.send(embed = embed)

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

                position = await Events(self.client).quarantine(member)

                # log the quarantine
                log_embed = Events(self.client).create_log_embed(
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
            view = Paginator("Quarantine Queue", guild.queue, generate = True)
            return await ctx.send(embed = view.pages[0], view = view)

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
        guild = await db.get()

        added = []
        removed = []

        embed = BaseEmbed()

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
                    await db.push_to_list('priority', channel.id)
                    added.append(channel.id)
                else:
                    await db.pull_from_list('priority', channel.id)
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
        guild = await db.get()

        added = []
        removed = []

        embed = BaseEmbed()

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
                    await db.push_to_list('allowed', role.id)
                    added.append(role.id)
                else:
                    await db.pull_from_list('allowed', role.id)
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
        loading = BaseEmbed(description = "Loading...")

        # gets an embed containing the cache (and a view, if the cache is not empty)
        msg = await ctx.send(embed = loading)
        embed, view = await e_or_s_list(ctx, msg, 'emoji')
        await msg.edit(embed = embed, view = view)

    @commands.command(aliases = ["stickers", "s"])
    @commands.has_permissions(manage_emojis_and_stickers = True)
    @commands.bot_has_permissions(manage_emojis_and_stickers = True)
    async def sticker(self, ctx: commands.Context):
        # same as emoji but for stickers
        loading = BaseEmbed(description = "Loading...")

        msg = await ctx.send(embed = loading)
        embed, view = await e_or_s_list(ctx, msg, 'sticker')
        await msg.edit(embed = embed, view = view)

    @commands.command(aliases = ["lock", "l"])
    @commands.has_permissions(manage_roles = True, kick_members = True, ban_members = True)
    async def lockdown(self, ctx: commands.Context):
        db = database.Guild(ctx.guild)
        guild = await db.get()

        embed = BaseEmbed()

        # toggle lockdown
        new_status = not guild.lockdown
        await db.set_field('lockdown', new_status)

        status = "enabled" if new_status else "disabled"
        embed.description = f"Lockdown has been {status}!"

        await ctx.send(embed = embed)

async def setup(bot: commands.Bot):
    await bot.add_cog(Automod(bot))