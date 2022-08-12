import discord
from discord.ext import commands
from discord.commands import SlashCommandGroup

from utils import database

from datetime import datetime, timedelta
from configparser import ConfigParser
import re

config = ConfigParser()
config.read("config.ini")

slash_guilds = [int(x) for x in str(config.get("server", "custom_ids")).split(', ')]

class custom(commands.Cog):
    def __init__(self, client):
        self.client: commands.Bot = client

    async def log_strike(
        self,
        ctx: discord.ApplicationContext, 
        log_id: int, 
        strike_difference: str,
        member: discord.Member,
        topic: str,
        action: str = None,
        removed: bool = False
    ):
        log = ctx.interaction.guild.get_channel(log_id)
        log_embed = discord.Embed(color = self.client.gray, timestamp = datetime.now())

        if removed:
            title = "Strike Removed"
            field_title = "From:"
        else:
            title = "Strike Added"
            field_title = "To:"
        
        log_embed.set_author(name = title, icon_url = member.display_avatar)
        log_embed.add_field(name = field_title, value = f"{member.mention}\nstrike {strike_difference}")
        log_embed.add_field(name = "By:", value = f"{ctx.author.mention}\nfor `{topic}`")

        if not removed:
            log_embed.set_footer(text = f"Action: {' '.join(action)}")

        await log.send(embed = log_embed)

    @commands.command(aliases = ["w"])
    @commands.has_permissions(administrator = True)
    async def watch(self, ctx: commands.Context, topic: str = None, *, intervals: str = None):
        db = database.Guild(ctx.guild)
        guild = await db.get()

        embed = discord.Embed(color = self.client.gray)

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

    async def topic_generator(ctx: discord.AutocompleteContext) -> list[str]:
        db = database.Guild(ctx.interaction.guild)
        guild = await db.get()

        return list(guild.strike_topics.keys())

    check = SlashCommandGroup(
        "check", 
        "Lists strikes for a user or topic", 
        checks = [
            commands.has_permissions(
                kick_members = True, 
                ban_members = True
            ).predicate
        ]
    )
    
    @check.command(guild_ids = slash_guilds, description = "Check a user's strikes", checks = check.checks)
    async def user(self, 
        ctx: discord.ApplicationContext, 
        member: discord.Option(discord.Member, "choose a member to check")
    ):
        db = database.Guild(ctx.guild)
        guild = await db.get()

        strikes = []

        for topic in guild.strike_topics:
            if str(member.id) in (t := guild.strike_topics[topic]["users"]):
                strikes.append((topic, t[str(member.id)][0]))

        embed = discord.Embed(color = self.client.gray)

        if not strikes:
            embed.description = f"{member.mention} hasn't been striked for anything yet"
        else:
            embed.set_author(name = f"{member.name}'s strikes", icon_url = member.display_avatar)

            for (topic, amount) in strikes:
                embed.add_field(name = topic, value = amount)

        await ctx.respond(embed = embed, ephemeral = True)
    
    @check.command(guild_ids = slash_guilds, description = "Check a topic's strikes", checks = check.checks)
    async def topic(self, 
        ctx: discord.ApplicationContext, 
        topic: discord.Option(str, "choose a topic to check", autocomplete = topic_generator)
    ):
        db = database.Guild(ctx.guild)
        guild = await db.get()

        user_list = [(user, strike, time) for user, (strike, time) in guild.strike_topics[topic]["users"].items()]
        embed = discord.Embed(color = self.client.gray)

        if not user_list:
            embed.description = f"nobody has been striked for `{topic}` so far"
        else:
            intervals = "`" + "` -> `".join(guild.strike_topics[topic]["intervals"]) + "`"
            embed.description = f"Strikes for **{topic}** ({intervals}):\n"

            users = "\n".join(f"<@{user}>" for (user, _, _) in user_list)
            strikes = "\n".join(f"{strike}" for (_, strike, _) in user_list)
            times = "\n".join(f"<t:{time}:R>" for (_, _, time) in user_list)

            embed.add_field(name = "User", value = users)
            embed.add_field(name = "Strikes", value = strikes)
            embed.add_field(name = "Last Updated", value = times)
        
        await ctx.respond(embed = embed, ephemeral = True)

    @discord.slash_command(guild_ids = slash_guilds, description = "Un-strike a member")
    @commands.has_permissions(kick_members = True, ban_members = True)
    async def unstrike(self,
        ctx: discord.ApplicationContext, 
        member: discord.Option(discord.Member, "choose a member to un-strike"),
        topic: discord.Option(str, "choose a strike topic", autocomplete = topic_generator)
    ):
        db = database.Guild(ctx.guild)
        guild = await db.get()

        embed = discord.Embed(color = self.client.gray)
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

            await self.log_strike(ctx, guild.log_id, strike_difference, member, topic, removed = True)

        await ctx.respond(embed = embed, ephemeral = True)

    @discord.slash_command(guild_ids = slash_guilds, description = "Strike a member for something")
    @commands.has_permissions(kick_members = True, ban_members = True)
    async def strike(self, 
        ctx: discord.ApplicationContext, 
        member: discord.Option(discord.Member, "choose a member to strike"), 
        topic: discord.Option(str, "choose a strike topic", autocomplete = topic_generator)
    ):
        db = database.Guild(ctx.guild)
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
                embed = discord.Embed(
                    description = f"{member.mention} has already been striked for `{topic}` in the last minute or so",
                    color = self.client.gray
                )

                return await ctx.respond(embed = embed, ephemeral = True)

            current_strike = user_info[0] + 1
        
        await db.set_field(f'strike_topics.{topic}.users.{str(member.id)}', [current_strike, now])
        
        # get the respective action for the strike
        if (i := current_strike) <= len(intervals):
            interval = intervals[i - 1]
        else:
            interval = intervals[-1]

        action = interval[0]

        if action not in ("m", "b"):
            await ctx.respond(f"**Error:** could not make the command, invalid action `{interval}`", ephemeral = True)

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
        
        if topic == "nsfw" and ctx.guild_id == 920012669090660414 and current_strike == 2:
            no_perm_roles = [
                ctx.guild.get_role(973744500189044837),
                ctx.guild.get_role(920166105488711750)
            ]
            perm_roles = [
                ctx.guild.get_role(920159184559931432),
                ctx.guild.get_role(920166390357438554)
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

        embed = discord.Embed(
            description = f"added a strike to {member.mention} for `{topic}` ({current_strike - 1} -> **{current_strike}**)\ncopy the command above (or long press if you're on mobile)",
            color = self.client.gray
        )

        if custom_removed:
            embed.description += "\n**(also removed image perms for you)**"

        await ctx.respond(cmd, embed = embed, ephemeral = True)
        await self.log_strike(ctx, guild.log_id, strike_difference, member, topic, action)

def setup(bot):
    bot.add_cog(custom(bot))