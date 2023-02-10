import discord
from discord.ext import commands
from discord import app_commands

from utils.views import Paginator, ConfirmView
from utils.base import BaseGroupCog
from utils import database

from configparser import ConfigParser
import typing

config = ConfigParser()
config.read("config.ini")

slash_guild = discord.Object(int(config.get("bot", "slash_guild")))

@app_commands.guilds(slash_guild)
class VC(BaseGroupCog, name = "vc", description = "user-vc commands"):
    async def vc_generator(self, interaction: discord.Interaction, current: str) -> list[str]:
        db = database.Guild(interaction.guild)
        guild = await db.get()
        vcs = {}

        for vc in guild.user_vcs:
            vc_info = guild.user_vcs.get(vc, {})
            status = ""

            if interaction.user.id in vc_info.get("waiting", []):
                status = "🔘"
            elif interaction.user.id in vc_info.get("accepted", []):
                status = "✅"
            elif interaction.user.id in vc_info.get("declined", []):
                status = "⛔"
            elif interaction.user.id == vc_info.get("user_id"):
                status = "👍"

            if channel := interaction.guild.get_channel(int(vc)):
                vcs[f"{status} {channel.name}".strip()] = str(channel.id)

        return [
            app_commands.Choice(name = name, value = value)
            for (name, value) in vcs.items() if current.lower() in name.lower()
        ]

    async def set_vc_entry(self, db: database.Guild, vc_id: int, user_id: int, successor_id: int = 0):
        await db.set_field(f"user_vcs.{vc_id}.user_id", user_id)
        await db.set_field(f"user_vcs.{vc_id}.successor_id", successor_id)

        vc_prefs = (await db.get()).vc_prefs.get(str(user_id), {})
        await db.set_field(f"user_vcs.{vc_id}.accepted", vc_prefs.get('trusted', []))
        await db.set_field(f"user_vcs.{vc_id}.declined", vc_prefs.get('blocked', []))
        await db.set_field(f"user_vcs.{vc_id}.waiting", [])

    @commands.Cog.listener()
    async def on_voice_state_update(self, member: discord.Member, before: discord.VoiceState, after: discord.VoiceState):
        db = database.Guild(member.guild)
        guild = await db.get()

        if (
            (vc := before.channel) and
            (not after.channel or vc.id != after.channel.id) and
            member.id == (vc_info := guild.user_vcs.get(str(vc.id), {})).get("user_id")
        ):
            if len(vc.members) > 0:
                if (successor := vc_info["successor_id"]) and any(m.id == successor for m in vc.members):
                    new_user_id = successor
                else:
                    new_user_id = vc.members[0].id

                await self.set_vc_entry(db, vc.id, new_user_id)
                await vc.edit(name = f"{member.guild.get_member(new_user_id).name}'s vc")
            else:
                await vc.delete()
                await db.del_field(f"user_vcs.{vc.id}")

        if after.channel and after.channel.id == guild.vc_make_id:
            creation_vc = member.guild.get_channel(guild.vc_make_id)
            vc = await member.guild.create_voice_channel(name = f"{member.name}'s vc", category = creation_vc.category, user_limit = 1)
            await member.move_to(vc)

            await self.set_vc_entry(db, vc.id, member.id)
            return

    @app_commands.command(description = "Ask to join someone's vc")
    @app_commands.autocomplete(vc = vc_generator)
    async def join(self, interaction: discord.Interaction, vc: str):
        db = database.Guild(interaction.guild)
        guild = await db.get()

        if not interaction.user.voice:
            return await interaction.response.send_message(f"**Error:** you need to be waiting in a vc", ephemeral = True)

        if vc not in guild.user_vcs:
            return await interaction.response.send_message(f"**Error:** they do not have their own vc", ephemeral = True)

        vc_info = guild.user_vcs[vc]
        vc_channel = interaction.guild.get_channel(int(vc))
        vc_owner = interaction.guild.get_member(vc_info["user_id"])

        if interaction.user.id == vc_owner.id:
            await interaction.response.send_message("**Error:** you can't ask to join your own vc", ephemeral = True)
            return

        if interaction.user in vc_channel.members:
            await interaction.response.send_message("**Error:** you are already in that vc", ephemeral = True)
            return

        if interaction.user.id in vc_info["waiting"]:
            await interaction.response.send_message("**Error:** you are already waiting to join that vc", ephemeral = True)
            return

        if interaction.user.id in vc_info["accepted"]:
            await interaction.user.move_to(interaction.guild.get_channel(int(vc)))
            await interaction.response.send_message("ok (previously accepted)", ephemeral = True)
            return

        if interaction.user.id in vc_info["declined"]:
            await interaction.response.send_message("**Error:** previously declined (if on accident, ask them to run /reset)", ephemeral = True)
            return

        await db.push_to_list(f"user_vcs.{vc}.waiting", interaction.user.id)

        waiting_msg = f"waiting for {vc_owner.mention} to accept.."
        await interaction.response.send_message(f"{waiting_msg} (stay in a vc so that you can be moved)", ephemeral = True)

        try:
            view = ConfirmView(vc_owner)
            dm_msg = await vc_owner.send(f"let {interaction.user} join your vc?", view = view)
            await view.wait()
        except discord.Forbidden:
            await interaction.edit_original_response(content = f"**Error:** can't send join request (not your fault, ask them to turn on DMs)")
            return

        if view.value:
            await dm_msg.edit(content = f"**accepted {interaction.user}'s request**", view = None)
            await interaction.edit_original_response(content = f"{waiting_msg} **accepted!**")
            await interaction.user.move_to(vc_channel)

            await db.push_to_list(f"user_vcs.{vc}.accepted", interaction.user.id)
        else:
            await dm_msg.edit(content = f"**declined {interaction.user}'s request**", view = None)
            await interaction.edit_original_response(content = f"{waiting_msg} **declined**")

            await db.push_to_list(f"user_vcs.{vc}.declined", interaction.user.id)

        await db.pull_from_list(f"user_vcs.{vc}.waiting", interaction.user.id)

    @app_commands.command(description = "Get a list of users who can/can't join your vc")
    async def users(self, interaction: discord.Interaction, kind: typing.Literal["trusted", "blocked", "accepted", "declined"]):
        db = database.Guild(interaction.guild)
        guild = await db.get()
        users = []

        if kind in ("trusted", "blocked"):
            vc_prefs = guild.vc_prefs.get(str(interaction.user.id), {})
            users = [interaction.guild.get_member(_).mention for _ in vc_prefs.get(kind, [])]
        elif kind in ("accepted", "declined"):
            vc = interaction.user.voice.channel.id if interaction.user.voice else 0
            users = [interaction.guild.get_member(_).mention for _ in guild.user_vcs.get(str(vc), {}).get(kind, [])]

        view = Paginator(f"{kind} users", users if users else ["none yet"])
        await interaction.response.send_message(embed = view.pages[0], view = view, ephemeral = True)

    @app_commands.command(description = "Trust/untrust someone for your vcs")
    async def trust(self, interaction: discord.Interaction, member: discord.Member):
        db = database.Guild(interaction.guild)
        guild = await db.get()

        if member.id == interaction.user.id:
            return await interaction.response.send_message("**Error:** what", ephemeral = True)

        trusted_users = guild.vc_prefs.get(str(interaction.user.id), {}).get("trusted", [])

        if member.id not in trusted_users:
            await db.push_to_list(f"vc_prefs.{interaction.user.id}.trusted", member.id)
            await db.pull_from_list(f"vc_prefs.{interaction.user.id}.blocked", member.id)

            await interaction.response.send_message(f"trusted {member.mention} (applies to new vcs)", ephemeral = True)
        else:
            await db.pull_from_list(f"vc_prefs.{interaction.user.id}.trusted", member.id)
            await interaction.response.send_message(f"untrusted {member.mention} (applies to new vcs)", ephemeral = True)

    @app_commands.command(description = "Block/unblock someone from your vcs")
    async def block(self, interaction: discord.Interaction, member: discord.Member):
        db = database.Guild(interaction.guild)
        guild = await db.get()

        if member.id == interaction.user.id:
            return await interaction.response.send_message("**Error:** what", ephemeral = True)

        blocked_users = guild.vc_prefs.get(str(interaction.user.id), {}).get("blocked", [])

        if member.id not in blocked_users:
            await db.push_to_list(f"vc_prefs.{interaction.user.id}.blocked", member.id)
            await db.pull_from_list(f"vc_prefs.{interaction.user.id}.trusted", member.id)

            await interaction.response.send_message(f"blocked {member.mention} (applies to new vcs)", ephemeral = True)
        else:
            await db.pull_from_list(f"vc_prefs.{interaction.user.id}.blocked", member.id)
            await interaction.response.send_message(f"unblocked {member.mention} (applies to new vcs)", ephemeral = True)

    @app_commands.command(description = "Resets the accepted/declined status of the user (for your vc)")
    async def reset(self, interaction: discord.Interaction, member: discord.Member):
        db = database.Guild(interaction.guild)
        guild = await db.get()

        if member.id == interaction.user.id:
            return await interaction.response.send_message("**Error:** why", ephemeral = True)

        if not (
            (voice := interaction.user.voice) and
            interaction.user.id == (guild.user_vcs.get(str(vc := voice.channel.id), {})).get("user_id")
        ):
            return await interaction.response.send_message(f"**Error:** you're not in a vc owned by you", ephemeral = True)

        await db.pull_from_list(f"user_vcs.{vc}.accepted", member.id)
        await db.pull_from_list(f"user_vcs.{vc}.declined", member.id)

        await interaction.response.send_message(f"reset {member.mention}'s join status", ephemeral = True)

    @app_commands.command(description = "Transfer ownership of your vc (when you leave)")
    async def successor(self, interaction: discord.Interaction, member: discord.Member):
        db = database.Guild(interaction.guild)
        guild = await db.get()

        if member.id == interaction.user.id:
            return await interaction.response.send_message(f"**Error:** you can't make yourself a successor", ephemeral = True)

        if not (
            (voice := interaction.user.voice) and
            interaction.user.id == guild.user_vcs.get((str(vc := voice.channel.id)), {}).get("user_id")
        ):
            return await interaction.response.send_message(f"**Error:** you're not in a vc owned by you", ephemeral = True)

        channel = member.guild.get_channel(vc)

        if member not in channel.members:
            return await interaction.response.send_message(f"**Error:** they aren't in your vc", ephemeral = True)

        await db.set_field(f"user_vcs.{vc}.successor_id", member.id)
        await interaction.response.send_message(f"made {member.mention} the successor to your vc", ephemeral = True)

    @app_commands.command(description = "Transfer ownership of your vc (now)")
    async def transfer(self, interaction: discord.Interaction, member: discord.Member):
        db = database.Guild(interaction.guild)
        guild = await db.get()

        if member.id == interaction.user.id:
            return await interaction.response.send_message(f"**Error:** you can't transfer a vc to yourself", ephemeral = True)

        if not (
            (voice := interaction.user.voice) and
            interaction.user.id == guild.user_vcs.get((str(vc := voice.channel.id)), {}).get("user_id")
        ):
            return await interaction.response.send_message(f"**Error:** you're not in a vc owned by you", ephemeral = True)

        channel = member.guild.get_channel(vc)

        if member not in channel.members:
            return await interaction.response.send_message(f"**Error:** they aren't in your vc", ephemeral = True)

        await channel.edit(name = f"{member.name}'s vc")
        await self.set_vc_entry(db, vc, member.id, interaction.user.id)
        await interaction.response.send_message(f"made {member.mention} the new vc owner", ephemeral = True)

    @app_commands.command(description = "Sets up user vc rooms")
    @app_commands.checks.has_permissions(administrator = True)
    async def setup(self, interaction: discord.Interaction, creation_vc: discord.VoiceChannel):
        await database.Guild(interaction.guild).set_field(f"vc_make_id", creation_vc.id)
        await interaction.response.send_message("ok")

async def setup(bot: commands.Bot):
  await bot.add_cog(VC(bot), guilds = [slash_guild])