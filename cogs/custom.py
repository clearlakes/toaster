import discord
from discord.ext import commands
from discord import app_commands


from utils.base import BaseCog, BaseEmbed
from utils.views import Paginator
from utils import database

from datetime import datetime, timedelta
from configparser import ConfigParser
import re

config = ConfigParser()
config.read("config.ini")

slash_guild = discord.Object(int(config.get("bot", "slash_guild")))

class Custom(BaseCog):
    async def log_strike(
        self,
        interaction: discord.Interaction,
        log_id: int,
        strike_difference: str,
        member: discord.Member,
        topic: str,
        action: str = None,
        removed: bool = False
    ):
        log = interaction.guild.get_channel(log_id)

        if not log:
            return  # if the log channel is missing don't do anything

        log_embed = BaseEmbed(timestamp = datetime.now())

        if removed:
            title = "Strike Removed"
            field_title = "From:"
        else:
            title = "Strike Added"
            field_title = "To:"

        log_embed.set_author(name = title, icon_url = member.display_avatar)
        log_embed.add_field(name = field_title, value = f"{member.mention}\nstrike {strike_difference}")
        log_embed.add_field(name = "By:", value = f"{interaction.user.mention}\nfor `{topic}`")

        if not removed:
            log_embed.set_footer(text = f"Action: {' '.join(action)}")

        await log.send(embed = log_embed)

    async def topic_generator(self, interaction: discord.Interaction, current: str) -> list[str]:
        db = database.Guild(interaction.guild)
        guild = await db.get()

        return [
            app_commands.Choice(name = t, value = t)
            for t in list(guild.strike_topics.keys()) if current.lower() in t.lower()
        ]

    async def remove_booster_roles(self, member: discord.Member):
        booster_roles = [member.guild.get_role(role_id) for role_id in [
                924460642319073310,
                924464072362164274,
                924461337478856876,
                924463602902110240,
                924462136313389056,
                924461859405455461,
                924460873769156668,
                920754099429986334,
                924462520859770910,
                924463093780738078
        ]]

        await member.remove_roles(*booster_roles)

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if (
            message.content == ";kevin" and
            message.guild.id == slash_guild.id and
            message.author.id != self.client.user.id
        ):
            await message.add_reaction("😃")

    @commands.Cog.listener()
    async def on_member_update(self, before: discord.Member, after: discord.Member):
        if (
            after.guild.id == slash_guild.id and
            before.premium_since is not None and
            after.premium_since is None  # boost ended
        ):
            await self.remove_booster_roles(after)

    @commands.command()
    @commands.is_owner()
    async def sync(self, ctx: commands.Context):
        await self.client.tree.sync(guild = slash_guild)  # updates slash commands
        await ctx.send("ok")

    @commands.command()
    @commands.has_permissions(administrator = True)
    async def rolesync(self, ctx: commands.Context):
        msg = await ctx.send("going through members.....")

        for member in ctx.guild.members:
            if member.premium_since is None:
                await self.remove_booster_roles(member)

        await msg.edit(content = "ok")

    @commands.command(aliases = ["w"])
    @commands.has_permissions(administrator = True)
    async def watch(self, ctx: commands.Context, topic: str = None, *, intervals: str = None):
        db = database.Guild(ctx.guild)
        guild = await db.get()

        embed = BaseEmbed()

        # list strike topics if nothing is given
        if not topic:
            if guild.strike_topics:
                topics = "Watching for:\n"

                # format intervals and topic name, along with total strikes
                for st in guild.strike_topics:
                    topic = guild.strike_topics[st]
                    total_strikes = 0

                    for user in topic['users']:
                        total_strikes += topic['users'][user][0]

                    intervals = '`' + '`, `'.join(topic['intervals']) + '`'

                    topics += f"**{st}** ({intervals}) - {total_strikes} total strikes\n"

                embed.description = topics
                embed.set_footer(text = "Use t!watch (topic) to remove a topic")
            else:
                embed.description = "not watching anything right now"

        # delete the topic if it exists
        elif guild.strike_topics and topic in guild.strike_topics:
            guild.strike_topics.pop(topic, None)
            await db.set_field(f'strike_topics', guild.strike_topics)

            embed.description = f"Removed topic **{topic}**."

        # add the topic if it doesn't exist
        else:
            if not intervals:
                return await ctx.send(f"**Error:** missing actions")

            await db.set_field(f'strike_topics.{topic}', {
                'intervals': intervals.split(),
                'users': {}
            })

            embed.description = f"Added topic **{topic}**."

        await ctx.send(embed = embed)

    check = discord.app_commands.Group(
        name = "check",
        description = "Lists strikes for a user or topic",
        default_permissions = discord.Permissions(kick_members = True, ban_members = True)
    )

    @check.command(description = "Check a user's strikes")
    @app_commands.describe(member = "choose a member to check")
    async def user(self, interaction: discord.Interaction, member: discord.Member):
        db = database.Guild(interaction.guild)
        guild = await db.get()

        user_strikes = []

        for t in guild.strike_topics:
            if (id := str(member.id)) in (st := guild.strike_topics[t]["users"]):
                user_strikes.append(tuple([t, *st[id]]))

        user_strikes.sort(key = lambda item: item[1], reverse = True)
        strike_list = [f"**{topic}** - `{strikes}` - <t:{time}:R>" for (topic, strikes, time) in user_strikes]

        if not strike_list:
            embed = BaseEmbed(description = f"{member.mention} hasn't been striked for anything yet")
            await interaction.response.send_message(embed = embed, ephemeral = True)
        else:
            view = Paginator(f"{member.name}'s strikes", strike_list)
            await interaction.response.send_message(embed = view.pages[0], view = view, ephemeral = True)

    @check.command(description = "Check a topic's strikes")
    @app_commands.describe(topic = "choose a topic to check")
    @app_commands.autocomplete(topic = topic_generator)
    async def topic(self, interaction: discord.Interaction, topic: str):
        db = database.Guild(interaction.guild)
        guild = await db.get()

        topic_strikes = []

        for u in (st := guild.strike_topics[topic]["users"]):
            topic_strikes.append(tuple([u, *st[u]]))

        topic_strikes.sort(key = lambda item: item[1], reverse = True)
        strike_list = [f"<@{user}> - `{strikes}` - <t:{time}:R> " for (user, strikes, time) in topic_strikes]

        if not strike_list:
            embed = BaseEmbed(description = f"nobody has been striked for `{topic}` so far")
            await interaction.response.send_message(embed = embed, ephemeral = True)
        else:
            view = Paginator(f"{topic} strikes", strike_list)
            await interaction.response.send_message(embed = view.pages[0], view = view, ephemeral = True)

    @app_commands.command(description = "Un-strike a member")
    @app_commands.describe(member = "choose a member to un-strike", topic = "choose a strike topic")
    @app_commands.autocomplete(topic = topic_generator)
    @app_commands.default_permissions(kick_members = True, ban_members = True)
    async def unstrike(self, interaction: discord.Interaction, member: discord.Member, topic: str):
        db = database.Guild(interaction.guild)
        guild = await db.get()

        embed = BaseEmbed()
        t = guild.strike_topics[topic]

        user_info = t['users'][str(member.id)] if str(member.id) in t['users'] else [0, None]

        if user_info[0] == 0:
            embed.description = f"{member.mention} has no strikes for `{topic}`"
        else:
            time_of_last_strike = user_info[1]
            new_strikes = user_info[0] - 1

            field = f'strike_topics.{topic}.users.{str(member.id)}'

            if new_strikes == 0:
                await db.del_field(field)  # delete the field if no strikes left
            else:
                await db.set_field(field, [new_strikes, time_of_last_strike])

            strike_difference = f"{user_info[0]} -> **{new_strikes}**"
            embed.description = f"removed a strike from {member.mention} for `{topic}` ({strike_difference})"

            await self.log_strike(interaction, guild.log_id, strike_difference, member, topic, removed = True)

        await interaction.response.send_message(embed = embed, ephemeral = True)

    @app_commands.command(description = "Strike a member for something")
    @app_commands.describe(member = "choose a member to strike", topic = "choose a strike topic")
    @app_commands.autocomplete(topic = topic_generator)
    @app_commands.default_permissions(kick_members = True, ban_members = True)
    async def strike(self, interaction: discord.Interaction, member: discord.Member, topic: str):
        db = database.Guild(interaction.guild)
        guild = await db.get()

        t = guild.strike_topics[topic]
        intervals: list[str] = t['intervals']

        now = int(datetime.now().timestamp())

        # increment the user's strikes (and store the previous value)
        if str(member.id) not in t['users']:
            current_strike = 1
        else:
            user_info = t['users'][str(member.id)]

            a_minute_ago = int((datetime.now() - timedelta(minutes = 1)).timestamp())

            if user_info[1] >= a_minute_ago:
                embed = BaseEmbed(description = f"{member.mention} has already been striked for `{topic}` in the last minute or so")
                return await interaction.response.send_message(embed = embed, ephemeral = True)

            current_strike = user_info[0] + 1

        await db.set_field(f'strike_topics.{topic}.users.{str(member.id)}', [current_strike, now])

        # get the respective action for the strike
        if (i := current_strike) <= len(intervals):
            interval = intervals[i - 1]
        else:
            interval = intervals[-1]

        action = interval[0]

        if action not in ("m", "b"):
            return await interaction.response.send_message(f"**Error:** could not make the command, invalid action `{interval}`", ephemeral = True)

        # multiply or add to punishment length if specified
        if len(num := re.findall(r'\d+', interval)) == 2:
            operation = interval[(interval.rfind(num[1]) - 1)]
            num = [int(n) for n in num]

            num[1] *= (current_strike - 1)

            if operation == "+":
                new_length = num[0] + num[1]
            elif operation == "*":
                new_length = num[0] * (num[1] if num[1] > 0 else 1)

            if new_length:
                interval = re.sub('\d+', str(new_length), interval.split(operation)[0])

        # create command using information from the selected action
        if action == "m":
            cmd = f";mute {member.id} {''.join(interval[1:])} {topic}"

        elif action == "b" and len(interval) > 1:
            cmd = f";tempban {member.id} {''.join(interval[1:])} {topic}"

        else:
            cmd = f";ban {member.id} {topic}"

        custom_removed = False

        if topic == "nsfw" and interaction.guild_id == 920012669090660414 and current_strike == 2:
            no_perm_roles = [
                interaction.guild.get_role(973744500189044837),
                interaction.guild.get_role(920166105488711750)
            ]
            perm_roles = [
                interaction.guild.get_role(920159184559931432),
                interaction.guild.get_role(920166390357438554)
            ]

            await member.add_roles(*no_perm_roles)
            await member.remove_roles(*perm_roles)

            custom_removed = True

        # remove semicolon and get command name with time interval
        action = cmd[1:].split(' ')[0::2]

        # if the command is just ;ban, remove the topic
        # (it would be the second string)
        if action[1] == topic:
            action.pop(1)

        strike_difference = f"{current_strike - 1} -> **{current_strike}**"

        embed = BaseEmbed(description = f"added a strike to {member.mention} for `{topic}` ({current_strike - 1} -> **{current_strike}**)\ncopy the command above (or long press if you're on mobile)")

        if custom_removed:
            embed.description += "\n**(also removed image perms for you)**"

        await interaction.response.send_message(cmd, embed = embed, ephemeral = True)
        await self.log_strike(interaction, guild.log_id, strike_difference, member, topic, action)

async def setup(bot: commands.Bot):
    await bot.add_cog(Custom(bot))