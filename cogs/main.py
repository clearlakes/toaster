import discord
from discord.ext import commands, pages
from utils.views import DropdownView, ConfirmView
from datetime import datetime, timedelta
from utils import database

class main(commands.Cog):
    def __init__(self, client):
        self.client = client

    @commands.Cog.listener()
    async def on_command_error(self, ctx: commands.Context, error: commands.CommandError):
        if isinstance(error, commands.BotMissingPermissions):
            # create a list of missing permissions
            perm_list = "- **" + "**\n- **".join(error.missing_permissions).replace("_", " ").title() + "**\n"

            # send an embed with the list
            embed = discord.Embed(
                description = f"**Error:** The bot is missing the following permissions:\n{perm_list}",
                color = discord.Color.brand_red()
            )

            await ctx.send(embed = embed)
        elif isinstance(error, commands.CheckFailure):
            # this appears every time the cog check in automod fails (server is not set up)
            pass
        else:
            raise error

    @commands.command()
    async def info(self, ctx: commands.Context):
        embed = discord.Embed(
            title = "toaster",
            description = "A bot that manages new accounts and helps prevent server nukes.\nUse `t!help` to see a list of commands.",
            color = self.client.gray
        )

        guild = database.Guild(ctx.guild).get()

        # add more information depending on if the guild has been set up
        if guild:
            actions = f"**{guild.actions}**"
            method = f"**{guild.method.capitalize()}**"

            embed.add_field(name = "Total Quarantined", value = actions)
            embed.add_field(name = "Method", value = method)
        else:
            embed.description += "\n**Run `t!setup` to use the quarantine commands.**"

        # get the uptime
        current_time = datetime.now()
        difference = current_time - self.client.initialized_at

        embed.add_field(name = "Uptime", value = f"**{str(difference).split('.')[0]}**")
        embed.set_thumbnail(url = self.client.user.display_avatar)
        embed.set_footer(text = "version 2 • made by buh#7797")

        await ctx.send(embed = embed)
    
    @commands.command()
    async def help(self, ctx: commands.Context):
        # page 1
        command_help = """
        `*` - optional
        `t!info` - lists information about the bot
        `t!setup` - sets up the quarantine functionality of the bot
        `t!toggle *[method]` - changes the mode of the bot
        `t!quarantine *[action]` - view and manage users in quarantine
        `t!priority *[channels]` - distinguishes important channels 
        `t!sticker` | `t!emoji` - view recently deleted emojis/stickers
        """

        # page 2
        perm_help = """
        **Required permissions (user):**
        `t!info` - none
        `t!setup` - administrator
        `t!toggle` - manage roles, kick/ban
        `t!quarantine` - manage roles, kick/ban
        `t!priority` - administrator
        `t!sticker` | `t!emoji` - manage emojis/stickers

        **Required permissions (bot):**
        manage emojis/roles/channels, kick/ban, view audit log, read message history
        """

        embeds = [
            discord.Embed(title = "Help - Commands", color = self.client.gray, description = command_help),
            discord.Embed(title = "Help - Permissions", color = self.client.gray, description = perm_help)
        ]
        
        # create a paginator that only shows one button at a time
        paginator = pages.Paginator(
            embeds, 
            show_disabled = False, 
            show_indicator = False,
            use_default_buttons = False,
            timeout = None
        )

        # rename buttons
        paginator.add_button(
            pages.PaginatorButton(
                "next", style=discord.ButtonStyle.secondary, label = "permissions"
            )
        )

        paginator.add_button(
            pages.PaginatorButton(
                "prev", style=discord.ButtonStyle.secondary, label = "commands"
            )
        )

        await paginator.send(ctx)

    @commands.command()
    @commands.has_permissions(administrator = True)
    @commands.bot_has_permissions(manage_emojis = True, manage_roles = True, manage_channels = True, kick_members = True, ban_members = True, view_audit_log = True, read_message_history = True)
    async def setup(self, ctx: commands.Context):
        db = database.Guild(ctx.guild)
        embed = discord.Embed(color = self.client.gray)

        # prevent user from running setup multiple times
        if db.exists():
            embed.description = "This server has been set up already!"
            return await ctx.send(embed = embed)

        # wait for the user to confirm setup
        embed.set_author(name = "Pre-Setup")
        embed.description = "After asking a bunch of questions, the bot will create:\n- a quarantine role\n- a log channel (if you don't have one yet)\n- a waiting room (for users in the queue)\n- a history channel (for looking at past quarantines)\n\nPress **ok** when you're ready!"

        view = ConfirmView(ctx)
        view.children[0].label = "ok"
        view.children[0].style = discord.ButtonStyle.gray
        view.remove_item(view.children[1])  # remove "idc" since it's not necessary

        main_msg = await ctx.send(embed = embed, view = view)
        await view.wait()

        if not view.value:
            return  # if for some reason they don't click "ok"

        embed.set_footer(text = ctx.message.guild.name, icon_url = ctx.message.guild.icon)

        # [question, text to display next to result]
        questions = [
            ["Select the method to use:", "method"],
            ["Select the channel to use for logs:", "log channel"],
            ["Select a minimum age for new accounts:", "minimum account age"],
            ["Watch for channel deletions?", "watching channels"],
            ["Watch for emoji/sticker deletions?", "watching emojis"],
            ["Watch for role deletions?", "watching roles"]
        ]

        # text used in the embed footer for each question
        notice = [
            "This will let the bot know what to do when a new account joins.",
            "User-specific quarantine channels will be made in the same category as this one.",
            "The bot will take action if their account's creation date is younger than what you select.",
            "This will make the bot quarantine users if they delete multiple channels in quick succession.",
            "Enabling this will make the bot save recently deleted emoji/stickers.",
            "This will make the bot quarantine users if they delete multiple roles in quick succession."
        ]

        results = []

        for index in range(len(questions)):
            # set embed details depending on step
            embed.set_author(name = f"Setup ({index + 1}/{len(questions)})")
            embed.set_footer(text = notice[index])
            embed.description = f"**{questions[index][0]}**"

            # dropdown selection used for most questions
            if index <= 2:
                kind = {0: 'method', 1: 'channel', 2: 'length of time'}
                view = DropdownView(kind[index], ctx)

            # switch to confirm view for yes/no questions
            elif index >= 3:
                view = ConfirmView(ctx)
            
            # edit the main message with the new question
            await main_msg.edit(embed = embed, view = view)

            await view.wait()

            # append result to list
            results.append(view.value)

        embed.set_author(name = "Finalizing Setup...", icon_url = ctx.message.guild.icon)
        embed.remove_footer()
        embed.description = ""

        await main_msg.edit(embed = embed, view = None)

        # create the quarantine role
        q_role = await ctx.message.guild.create_role(name = 'quarantine', color = 0x200841)

        # disable view channel permissions for the quarantine role
        for channel in ctx.message.guild.channels:
            try:
                await channel.set_permissions(q_role, view_channel = False)
            except discord.Forbidden:
                pass

        results.append(q_role.id)

        # used for creating private channels (allow_q -> quarantined people can see it)
        make_private = lambda allow_q: {
            ctx.message.guild.self_role: discord.PermissionOverwrite(view_channel = True),
            ctx.message.guild.default_role: discord.PermissionOverwrite(view_channel = False),
            q_role: discord.PermissionOverwrite(view_channel = True if allow_q else False, send_messages = False)
        }

        # send embed to #waiting-room explaining what it is for queued users
        wait_embed = discord.Embed(
            title = "Waiting Room",
            description = "If you are seeing this message, many new accounts are joining at this time. Please wait until a moderator is able to see you!",
            color = discord.Color.og_blurple()
        )

        waitroom = await ctx.message.guild.create_text_channel(name = 'waiting-room', overwrites = make_private(True))
        await waitroom.send(embed = wait_embed)

        results.append(waitroom.id)

        # create #toaster-history
        history = await ctx.message.guild.create_text_channel(name = 'toaster-history', overwrites = make_private(False))
        results.append(history.id)

        db.add_guild(*results)

        embed.title = f"Setup Complete"
        embed.set_footer(text = "View the new commands you can use with t!help")
        embed.color = discord.Color.brand_green()
        embed.remove_author()

        setup_info = ""

        # display results
        for index, (result, result_desc) in enumerate(zip(results, [q[1] for q in questions])):          
            if index == 1:
                # render channel with its id
                result = f'<#{result}>'
            elif index == 2:
                # render seconds as days
                result = str(timedelta(seconds = int(result))).split(',')[0]

            # add to result list (replace methods used for yes/no questions)    
            setup_info += f"{result_desc.capitalize()}: **{result}**\n".replace('True', 'Yes').replace('False', 'No')

        setup_info += f"**Created <@&{q_role.id}>, <#{waitroom.id}>, and <#{history.id}>** (do not delete these!)"

        embed.description = setup_info
        
        await main_msg.edit(embed = embed, view = None)

def setup(bot):
    bot.add_cog(main(bot))