import discord
from discord.ext import commands

from utils import database

from configparser import ConfigParser
from datetime import datetime
import re

config = ConfigParser()
config.read("config.ini")

slash_guilds = [int(x) for x in str(config.get("server", "custom_ids")).split(', ')]

class custom(commands.Cog):
    def __init__(self, client):
        self.client = client
    
    @commands.command(aliases = ["w"])
    @commands.has_permissions(administrator = True)
    async def watch(self, ctx: commands.Context, topic: str = None, *, intervals: str = None):
        db = database.Guild(ctx.guild)
        guild = db.get()

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
                        total_strikes += topic['users'][user]

                    intervals = '`' + '`, `'.join(topic['intervals']) + '`'

                    topics += f"**{st}** ({intervals}) - {total_strikes} total strikes\n"
                
                embed.description = topics
                embed.set_footer(text = "Use t!watch (topic) to remove a topic")
            else:
                embed.description = "not watching anything right now"

        # delete the topic if it exists 
        elif guild.strike_topics and topic in guild.strike_topics:
            guild.strike_topics.pop(topic, None)
            db.set_field(f'strike_topics', guild.strike_topics)

            embed.description = f"Removed topic **{topic}**."

        # add the topic if it doesn't exist
        else:
            if not intervals:
                return await ctx.send(f"**Error:** missing actions")

            db.set_field(f'strike_topics.{topic}', {
                'intervals': intervals.split(),
                'users': {}
            })

            embed.description = f"Added topic **{topic}**."

        await ctx.send(embed = embed)

    async def topic_generator(ctx: discord.AutocompleteContext) -> list[str]:
        db = database.Guild(ctx.interaction.guild)
        guild = db.get()

        return list(guild.strike_topics.keys())

    @discord.slash_command(guild_ids = slash_guilds, description = "Strike a member for something")
    @commands.has_permissions(kick_members = True, ban_members = True)
    async def strike(self, 
        ctx: discord.ApplicationContext, 
        member: discord.Option(discord.Member, "choose a member to strike"), 
        topic: discord.Option(str, "choose a strike topic", autocomplete = topic_generator)
    ):
        db = database.Guild(ctx.guild)
        guild = db.get()

        t = guild.strike_topics[topic]
        intervals: list[str] = t['intervals']
        
        # increment the user's strikes (and store the previous value)
        if str(member.id) not in t['users']:
            current_strike = 1
        else:
            current_strike = t['users'][str(member.id)] + 1
        
        db.set_field(f'strike_topics.{topic}.users.{str(member.id)}', current_strike)
        
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

            num[1] *= current_strike
            
            if operation == "+":
                new_length = num[0] + num[1]
            elif operation == "*":
                new_length = num[0] * num[1]
            
            if new_length:
                interval = re.sub('\d+', str(new_length), interval.split(operation)[0])

        # create command using information from the selected action
        if action == "m":
            cmd = f";mute {member.id} {''.join(interval[1:])} {topic}"

        elif action == "b" and len(interval) > 1:
            cmd = f";tempban {member.id} {''.join(interval[1:])} {topic}"

        else:
            cmd = f";ban {member.id} {topic}"
        
        # remove semicolon and get command name with time interval
        action = cmd[1:].split(' ')[0::2]

        # if the command is just ;ban, remove the topic 
        # (it would be the second string)
        if action[1] == topic:
            action.pop(1)

        strike_difference = f"{current_strike - 1} -> **{current_strike}**"

        embed = discord.Embed(
            description = f"{member.mention} `{topic}` strikes: {current_strike - 1} -> **{current_strike}**\ncopy the command above (or long press if you're on mobile)",
            color = self.client.gray
        )

        await ctx.respond(cmd, embed = embed, ephemeral = True)

        log = ctx.interaction.guild.get_channel(guild.log_id)
        log_embed = discord.Embed(color = self.client.gray, timestamp = datetime.now())

        log_embed.set_author(name = "Strike Added", icon_url = member.display_avatar)
        log_embed.add_field(name = "To:", value = f"{member.mention}\nstrike {strike_difference}")
        log_embed.add_field(name = "By:", value = f"{ctx.author.mention}\nfor `{topic}`")
        log_embed.set_footer(text = f"Action: {' '.join(action)}")

        await log.send(embed = log_embed)

def setup(bot):
    bot.add_cog(custom(bot))