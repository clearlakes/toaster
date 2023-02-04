import discord
from discord.ext import commands
from discord import app_commands

from utils.views import Paginator, ConfirmView
from utils.base import BaseCog, BaseEmbed
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

    async def vc_generator(self, interaction: discord.Interaction, current: str) -> list[str]:
        db = database.Guild(interaction.guild)
        guild = await db.get()

        if not guild.user_vcs:
            return []

        vcs = [interaction.guild.get_channel(int(vc)) for vc in guild.user_vcs]

        return [
            app_commands.Choice(name = v.name, value = str(v.id))
            for v in vcs if v and current.lower() in v.name.lower()
        ]

    @commands.Cog.listener()
    async def on_voice_state_update(self, member: discord.Member, before: discord.VoiceState, after: discord.VoiceState):
        db = database.Guild(member.guild)
        guild = await db.get()

        if not guild.vc_make_id or not guild.vc_wait_id:
            return

        if after.channel and after.channel.id == guild.vc_make_id:
            creation_vc = member.guild.get_channel(guild.vc_make_id)
            vc = await member.guild.create_voice_channel(name = f"{member.name}'s vc", category = creation_vc.category, user_limit = 1)
            await member.move_to(vc)

            await db.set_field(f"user_vcs.{vc.id}.user_id", member.id)
            await db.set_field(f"user_vcs.{vc.id}.successor_id", None)
            return

        if ((before.channel and not after.channel) or (before.channel.id != after.channel.id)) and str(before.channel.id) in guild.user_vcs:
            vc_info = guild.user_vcs[str(before.channel.id)]

            if member.id == vc_info["user_id"]:
                if len(before.channel.members) > 0:
                    if (successor := vc_info["successor_id"]) and any(m.id == successor for m in before.channel.members):
                        new_user_id = successor
                    else:
                        new_user_id = before.channel.members[0].id

                    await db.set_field(f"user_vcs.{before.channel.id}.user_id", new_user_id)
                    await db.set_field(f"user_vcs.{before.channel.id}.successor_id", None)

                    new_user = member.guild.get_member(new_user_id)
                    await before.channel.edit(name = f"{new_user.name}'s vc")
                else:
                    await before.channel.delete()
                    await db.del_field(f"user_vcs.{before.channel.id}")

    @app_commands.command(description = "Ask to join someone's vc")
    @app_commands.autocomplete(vc = vc_generator)
    @app_commands.checks.cooldown(1, 10, key = lambda i: (i.guild_id, i.user.id))
    @app_commands.guilds(slash_guild)
    async def join(self, interaction: discord.Interaction, vc: str):
        guild = await database.Guild(interaction.guild).get()

        if not (user_voice := interaction.user.voice) or user_voice.channel.id != guild.vc_wait_id:
            return await interaction.response.send_message(f"**Error:** you need to be waiting in <#{guild.vc_wait_id}>", ephemeral = True)

        if not guild.user_vcs or vc not in guild.user_vcs:
            return await interaction.response.send_message(f"**Error:** they do not have their own vc", ephemeral = True)

        vc_info = guild.user_vcs[vc]
        vc_owner = interaction.guild.get_member(vc_info["user_id"])

        waiting_msg = f"waiting for {vc_owner.mention} to accept.."
        await interaction.response.send_message(f"{waiting_msg} (stay in <#{guild.vc_wait_id}> so that you can be moved)", ephemeral = True)

        view = ConfirmView(vc_owner)
        dm_msg = await vc_owner.send(f"let {interaction.user} join your vc?", view = view)
        await view.wait()

        if view.value:
            await dm_msg.edit(content = f"**accepted {interaction.user}'s request**", view = None)
            await interaction.edit_original_response(content = f"{waiting_msg} **accepted!**")
            await interaction.user.move_to(interaction.guild.get_channel(int(vc)))
        else:
            await dm_msg.edit(content = f"**declined {interaction.user}'s request**", view = None)
            await interaction.edit_original_response(content = f"{waiting_msg} **declined**")

    @join.error
    async def _join_error(self, interaction: discord.Interaction, error: app_commands.AppCommandError):
        if isinstance(error, app_commands.CommandOnCooldown):
            await interaction.response.send_message(f"**Error:** cooldown (wait {round(error.retry_after)}s)", ephemeral = True)
        else:
            raise error

    @app_commands.command(description = "Transfer ownership of your vc (when you leave)")
    @app_commands.guilds(slash_guild)
    async def successor(self, interaction: discord.Interaction, member: discord.Member):
        db = database.Guild(interaction.guild)
        guild = await db.get()

        if not guild.user_vcs or not (vc := [v for v in guild.user_vcs if guild.user_vcs[v]["user_id"] == interaction.user.id]):
            return await interaction.response.send_message(f"**Error:** you're not in a vc owned by you", ephemeral = True)

        if member.id == interaction.user.id:
            return await interaction.response.send_message(f"**Error:** you can't make yourself a successor", ephemeral = True)

        vc = vc[0]
        channel = member.guild.get_channel(int(vc))

        if member not in channel.members:
            return await interaction.response.send_message(f"**Error:** they aren't in your vc", ephemeral = True)

        await db.set_field(f"user_vcs.{vc}.successor_id", member.id)
        await interaction.response.send_message(f"made {member.mention} the successor to your vc", ephemeral = True)

    @app_commands.command(description = "Transfer ownership of your vc (now)")
    @app_commands.guilds(slash_guild)
    async def transfer(self, interaction: discord.Interaction, member: discord.Member):
        db = database.Guild(interaction.guild)
        guild = await db.get()

        if not guild.user_vcs or not (vc := [v for v in guild.user_vcs if guild.user_vcs[v]["user_id"] == interaction.user.id]):
            return await interaction.response.send_message(f"**Error:** you're not in a vc owned by you", ephemeral = True)

        if member.id == interaction.user.id:
            return await interaction.response.send_message(f"**Error:** you can't transfer a vc to yourself", ephemeral = True)

        vc = vc[0]
        channel = member.guild.get_channel(int(vc))

        if member not in channel.members:
            return await interaction.response.send_message(f"**Error:** they aren't in your vc", ephemeral = True)

        await db.set_field(f"user_vcs.{vc}.user_id", member.id)
        await db.set_field(f"user_vcs.{vc}.successor_id", interaction.user.id)

        await channel.edit(name = f"{member.name}'s vc")
        await interaction.response.send_message(f"made {member.mention} the new vc owner", ephemeral = True)

    @app_commands.command(description = "Sets up user vc rooms")
    @app_commands.checks.has_permissions(administrator = True)
    @app_commands.guilds(slash_guild)
    async def vcsetup(self, interaction: discord.Interaction, creation_vc: discord.VoiceChannel, waiting_vc: discord.VoiceChannel):
        db = database.Guild(interaction.guild)
        await db.set_field(f"vc_make_id", creation_vc.id)
        await db.set_field(f"vc_wait_id", waiting_vc.id)

        await interaction.response.send_message("ok")

    @commands.command()
    @commands.is_owner()
    async def sync(self, ctx: commands.Context):
        await self.client.tree.sync(guild = slash_guild)  # updates slash commands
        await ctx.send("ok")

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
    @app_commands.guilds(slash_guild)
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
    @app_commands.guilds(slash_guild)
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