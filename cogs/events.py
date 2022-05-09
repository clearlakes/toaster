import discord
from discord import abc
from discord.ext import commands
from datetime import datetime, timedelta
from utils import database
from typing import Union
import io

class events(commands.Cog):
    def __init__(self, client):
        self.client = client

    def find_missing(self, before, after):
        """Finds the difference between two lists."""
        if len(before) > len(after):
            return next(iter(set(before) - set(after)))

    def create_log_embed(self, title: str, member: discord.Member, reason: str = None, extra = None):
        """Generates embeds for logging quarantines."""
        embed = discord.Embed(
            title = title,
            description = f"{member.mention}\n{member} | ID: {member.id}",
            color = discord.Color.red() if not reason else discord.Color.dark_red()
        )

        # sets the reason for the quarantine (assumes new account if no reason is given)
        embed.add_field(name = "Reason:", value = reason if reason else f"New account!\n(created at <t:{int(member.created_at.timestamp())}>)")

        if extra:
            # show either the user's quarantine channel or queue position
            embed.add_field(name = "Quarantine:", value = extra)

        embed.set_thumbnail(url = member.display_avatar)
        embed.timestamp = datetime.now()

        return embed
    
    async def quarantine(self, db_guild: database.Guild, db_doc: database.Document, member: discord.Member, log: discord.TextChannel):
        """Either quarantines or enqueues users."""
        q_role = member.guild.get_role(db_doc.q_role_id)
        await member.add_roles(q_role)
        db_guild.increment()

        # quarantine the user if there are less than 5 active ones (else, add them to the queue)
        if len(db_doc.quarantine) < 5:
            # allow only the member and the bot to view the channel
            overwrites = {
                member.guild.default_role: discord.PermissionOverwrite(read_messages = False),
                member: discord.PermissionOverwrite(
                    view_channel = True,
                    attach_files = False,
                    use_external_emojis = False
                ),
                member.guild.me: discord.PermissionOverwrite(view_channel = True)
            }

            # allow roles in guild.allowed to view quarantine
            if db_doc.allowed:
                for role_id in db_doc.allowed:
                    role = await member.guild.get_role(role_id)
                    overwrites[role] = discord.PermissionOverwrite(view_channel = True)

            # hide the waiting room from the member
            waitroom = member.guild.get_channel(db_doc.wait_id)
            await waitroom.set_permissions(member, view_channel = False)

            # create the quarantine channel
            channel = await member.guild.create_text_channel(f"quarantine-{member.name.replace(' ', '')[0:5]}", overwrites = overwrites, category = log.category)
            db_guild.add_quarantine(member.id, channel.id)

            return f"<#{channel.id}>"
        else:
            db_guild.push_to_list('queue', member.id)
            return f"Queued - #{len(db_doc.queue) + 1}"

    async def remove_quarantine(self, member: discord.Member, reason: str):
        """Removes a user from quarantine/the queue."""
        db = database.Guild(member.guild)
        guild = db.get()

        member_id = str(member.id)

        if guild is None:
            return

        if member_id in guild.quarantine or member.id in guild.queue:
            # bakcup and delete the quarantine channel if the user was being quarantined (else, remove them from the queue)
            if member_id in guild.quarantine:
                what = f"Ended quarantine of {member} ({reason})"
                
                channel: discord.TextChannel = await self.client.fetch_channel(guild.quarantine[member_id])
                
                # backup might take a while
                saving = discord.Embed(
                    description = "Saving channel messages... (this might take a while)",
                    color = self.client.gray
                )

                await channel.send(embed = saving)

                history_log = ''

                # iterate over messages in the channel
                async for message in channel.history(oldest_first = True):
                    # ignore messages made by the bot
                    if message.author == message.guild.me:
                        continue
                    
                    # add message to the history log
                    date = message.created_at.strftime("%m/%d/%Y %H:%M:%S")
                    msg = (message.content.replace('\n', ' ').replace('  ', ' ') + ' ') if message.content else ''
                    history_log += f"[{date}] {message.author} > {msg}" + ' '.join(map(str, message.attachments)) + '\n'

                history: discord.TextChannel = await self.client.fetch_channel(guild.history)
                
                # send the history log as a text file
                if history_log != '':
                    await history.send(file = discord.File(fp = io.BytesIO(history_log.encode("utf8")), filename = f"{member.id}_quarantine.txt"))

                await channel.delete()
            else:
                what = f"Removed {member} from the queue ({reason})"

            # remove the quarantine from the guild's database
            db.del_quarantine(member.id)
            
            # add an entry to the log channel
            log = member.guild.get_channel(guild.log_id)
            embed = discord.Embed()

            embed.set_author(name = what, icon_url = member.display_avatar)
            embed.color = self.client.gray

            await log.send(embed = embed)

            # if the user was in a quarantine channel, pull in the next person in the queue
            if member_id in guild.quarantine and len(guild.queue) > 0 and guild.method == 'quarantine':
                guild = db.get()
                next_member = member.guild.get_member(guild.queue[0])

                db.pull_from_list('queue', next_member.id)
                await self.quarantine(db, guild, next_member, log)

                embed.set_author(name = f"Moved {next_member} into quarantine #{len(guild.quarantine) + 1}", icon_url = next_member.display_avatar)
                embed.color = discord.Color.dark_purple()

                await log.send(embed = embed)
        
    async def log_action(self, deleted: Union[discord.abc.GuildChannel, discord.Emoji, discord.GuildSticker, discord.Role]):
        """Adds entries for when something is deleted."""
        db = database.Guild(deleted.guild)
        guild = db.get()

        if guild is None:
            return

        # do not log certain events if they weren't enabled during setup

        if not guild.watching_roles and isinstance(deleted, discord.Role):
            return
        
        if not guild.watching_channels and isinstance(deleted, discord.abc.GuildChannel):
            return
        
        if not guild.watching_emojis and isinstance(deleted, (discord.Emoji, discord.GuildSticker)):
            return
        
        if isinstance(deleted, (discord.abc.GuildChannel, discord.Role)):
            # use different caches and audit log entries depending on what was deleted
            if isinstance(deleted, discord.Role):
                entry = await deleted.guild.audit_logs(action=discord.AuditLogAction.role_delete, limit=1).get()
                cache = guild.role_cache
                kind = ["@", "role"]
            else:
                entry = await deleted.guild.audit_logs(action=discord.AuditLogAction.channel_delete, limit=1).get()
                cache = guild.channel_cache
                kind = ["#", "channel"]

            # make the bot ignore itself
            if entry.user == entry.guild.me:
                return

            if entry.user == entry.guild.owner:
                return

            # if what was deleted was not prioritized, check if other things were deleted as well
            if deleted.id not in guild.priority:
                now = datetime.now()
                five_minutes_ago = int((now - timedelta(minutes=5)).timestamp())

                # list every deletion entry that happened in the last 5 minutes
                amount_deleted = [log_entry for log_entry in reversed(cache) if log_entry[0] >= five_minutes_ago and log_entry[1] == entry.user.id]

                # if less than three things were deleted, add it as an entry
                if len(amount_deleted) < 3:
                    # clear the cache if it has 10 or more entries in it
                    if len(cache) >= 10:
                        db.clear_list(f'{kind[1]}_cache')

                    entry = [int(now.timestamp()), entry.user.id, deleted.name]
                    db.push_to_list(f'{kind[1]}_cache', entry)
                    return
                
                # list what was deleted as the reason
                reason = f"deleted {kind[1]}s:\n**- {kind[0]}" + f"\n- {kind[0]}".join([log_entry[2] for log_entry in amount_deleted]) + "**"
            else:
                reason = f"deleted **{kind[0]}{deleted.name}** (priority)"

            # if a bot deleted the channels, kick it and instead get the user that added it
            if entry.user.bot:
                await entry.user.kick()

                entry = await deleted.guild.audit_logs(action=discord.AuditLogAction.bot_add, limit=1).get()
                reason = "added a bot that " + reason
            
            # remove roles from the user that have the following permissions, so that they can't do more harm
            perms_to_remove = [
                'kick_members',
                'ban_members',
                'manage_channels',
                'manage_emojis',
                'manage_roles'
            ]

            roles_to_remove = [role for role in entry.user.roles if any(dict(role.permissions)[perm] for perm in perms_to_remove)]
            await entry.user.remove_roles(*roles_to_remove)

            # log the quarantine
            log = deleted.guild.get_channel(guild.log_id)
            extra = await self.quarantine(db, guild, entry.user, log) 

            embed = self.create_log_embed("Quarantined Member", entry.user, reason.capitalize(), extra = extra)
            
            # list roles that were removed from the user
            if roles_to_remove:
                embed.add_field(name = "Took away:", value = ', '.join([f'<@&{r.id}>' for r in roles_to_remove]))

            return await log.send(embed = embed)

        # cache emojis and stickers
        elif isinstance(deleted, discord.Emoji):
            return db.push_to_list('emoji_cache', [deleted.id, deleted.name])

        elif isinstance(deleted, discord.GuildSticker):
            return db.push_to_list('sticker_cache', [deleted.id, deleted.name])

    @commands.Cog.listener()
    async def on_guild_remove(self, guild: discord.Guild):
        # remove the guild from the database if they kick the bot
        database.Guild(guild).delete()
    
    @commands.Cog.listener()
    async def on_guild_emojis_update(self, guild, before, after):
        # since you can't get the deleted emoji directly,
        # find the difference between the emoji list before the update and after
        deleted_emoji = self.find_missing(before, after)

        if deleted_emoji:
            await self.log_action(deleted_emoji)
    
    @commands.Cog.listener()
    async def on_guild_stickers_update(self, guild, before, after):
        # use the same process as emojis to find deleted stickers
        deleted_sticker = self.find_missing(before, after)
        
        if deleted_sticker:
            await self.log_action(deleted_sticker)
    
    @commands.Cog.listener()
    async def on_guild_channel_delete(self, channel: abc.GuildChannel):
        await self.log_action(channel)
    
    @commands.Cog.listener()
    async def on_guild_role_delete(self, role: discord.Role):
        await self.log_action(role)

    @commands.Cog.listener()
    async def on_member_remove(self, member: discord.Member):
        # remove a member from quarantine/queue if they leave (or if they are kicked)
        await self.remove_quarantine(member, "left")
    
    @commands.Cog.listener()
    async def on_member_ban(self, guild: discord.Guild, member: discord.Member):
        # remove a member from quarantine/queue if they are banned
        await self.remove_quarantine(member, "banned")
    
    @commands.Cog.listener()
    async def on_member_update(self, before: discord.Member, after: discord.Member):
        deleted_role = self.find_missing(before.roles, after.roles)

        if deleted_role:
            guild = database.Guild(after.guild).get()

            if guild is None:
                return

            # check if the user had the quarantine role removed from them
            if deleted_role.id == guild.q_role_id:
                await self.remove_quarantine(after, "cleared")

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        db = database.Guild(member.guild)
        guild = db.get()
        extra = None

        if guild is None:
            return
        
        # do nothing if the bot was set to ignore new accounts
        if guild.method == 'ignore':
            return

        # get the account's age in seconds
        account_age = int((member.created_at.replace(tzinfo = None) - datetime.now()).total_seconds())

        # do nothing if the account is not new
        if account_age > guild.min_age:
            return

        log = member.guild.get_channel(guild.log_id)

        # manage the account according to the method

        if guild.method == 'quarantine':
            extra = await self.quarantine(db, guild, member, log)
            action = "Quarantined"

        elif guild.method == 'kick':
            await member.kick()
            action = "Kicked"

        elif guild.method == 'ban':
            await member.ban()
            action = "Banned"

        # log the action
        embed = self.create_log_embed(f"{action} Member", member, extra = extra)

        await log.send(embed = embed)

def setup(bot):
    bot.add_cog(events(bot))