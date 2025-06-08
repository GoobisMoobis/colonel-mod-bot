import os
import re
import threading
import discord
from discord.ext import commands
from discord import app_commands, Interaction, Embed
import web  # FastAPI web server file

TOKEN = os.environ.get("DISCORD_TOKEN")
LOG_CHANNEL_ID = int(os.environ.get("LOG_CHANNEL_ID", 0))
GUILD_ID = int(os.environ.get("GUILD_ID", 0)) or None

intents = discord.Intents.default()
intents.message_content = True
intents.members = True
intents.guilds = True

bot = commands.Bot(command_prefix="!", intents=intents, help_command=None)

# Regex patterns
raw_patterns = [
    r"badword1",
    r"\bforbidden\b",
    r"somepattern\d+"
]
regex_list = [re.compile(pat, re.IGNORECASE) for pat in raw_patterns]

# --- Shared Help Embed ---
def get_help_embed() -> Embed:
    embed = Embed(title="Bot Commands Help", color=discord.Color.blurple())
    embed.add_field(name="/echo [message] (channel)", value="Make the bot say something. Channel is optional.", inline=False)
    embed.add_field(name="!echo [#channel] message", value="Same as above, deletes the trigger message. Requires Manage Messages.", inline=False)
    embed.add_field(name="/help | !help", value="Shows this help message", inline=False)
    return embed

# --- Events ---
@bot.event
async def on_ready():
    print(f"Logged in as {bot.user}")
    if GUILD_ID:
        try:
            synced = await bot.tree.sync(guild=discord.Object(id=GUILD_ID))
            print(f"Synced {len(synced)} command(s) to guild {GUILD_ID}")
        except Exception as e:
            print(f"Failed to sync commands: {e}")

@bot.event
async def on_message(message: discord.Message):
    if message.author.bot:
        return

    # Check regex matches
    if not any(r.search(message.content) for r in regex_list):
        return

    message_deleted = False
    member_notified = False
    member_timed_out = False

    try:
        await message.reply("This word is not allowed here")
        member_notified = True
    except Exception:
        pass

    try:
        await message.delete()
        message_deleted = True
    except Exception:
        pass

    try:
        if message.guild.me.guild_permissions.moderate_members:
            await message.author.timeout(discord.utils.utcnow() + discord.timedelta(minutes=5), reason="AutoMod violation")
            member_timed_out = True
    except Exception:
        pass

    embed = discord.Embed(
        title="AutoMod triggered!",
        color=discord.Color.red(),
        timestamp=discord.utils.utcnow()
    )
    embed.add_field(name="Message deleted?", value="✅" if message_deleted else "❌", inline=True)
    embed.add_field(name="Member notified?", value="✅" if member_notified else "❌", inline=True)
    embed.add_field(name="Member timed out?", value="✅" if member_timed_out else "❌", inline=True)
    embed.set_footer(text=f"User: {message.author}", icon_url=message.author.display_avatar.url)

    try:
        log_channel = await bot.fetch_channel(LOG_CHANNEL_ID)
        await log_channel.send(embed=embed)
    except Exception as e:
        print("Failed to log incident:", e)

    await bot.process_commands(message)

# --- /help Slash Command ---
@bot.tree.command(name="help", description="Show the list of commands", guild=discord.Object(id=GUILD_ID))
async def slash_help(interaction: Interaction):
    embed = get_help_embed()
    await interaction.response.send_message(embed=embed, ephemeral=True)

# --- !help Command ---
@bot.command(name="help", help="Show the help message")
async def help_command(ctx: commands.Context):
    embed = get_help_embed()
    await ctx.send(embed=embed)

# --- /echo Slash Command ---
@bot.tree.command(name="echo", description="Make the bot say something", guild=discord.Object(id=GUILD_ID))
@app_commands.describe(message="The message to send", channel="The channel to send it in (optional)")
async def slash_echo(interaction: Interaction, message: str, channel: discord.TextChannel = None):
    if not interaction.user.guild_permissions.manage_messages:
        embed = discord.Embed(
            title="Permission Denied",
            description="You need the **Manage Messages** permission to use this command.",
            color=discord.Color.red()
        )
        return await interaction.response.send_message(embed=embed, ephemeral=True)

    target_channel = channel or interaction.channel
    await target_channel.send(message)
    await interaction.response.send_message(f"✅ Sent in {target_channel.mention}", ephemeral=True)

# --- !echo Command ---
@bot.command(name="echo", help="Make the bot say something. Usage: !echo [#channel] message")
@commands.has_permissions(manage_messages=True)
async def echo(ctx: commands.Context, *args):
    await ctx.message.delete()

    if not args:
        return await ctx.send("⚠️ Please provide a message to echo.")

    target_channel = ctx.channel
    if args[0].startswith("<#") and args[0].endswith(">"):
        try:
            channel_id = int(args[0][2:-1])
            channel = ctx.guild.get_channel(channel_id)
            if isinstance(channel, discord.TextChannel):
                target_channel = channel
                args = args[1:]
        except Exception:
            pass

    message = " ".join(args)
    await target_channel.send(message)

# --- !echo Error Handler ---
@echo.error
async def echo_error(ctx: commands.Context, error):
    if isinstance(error, commands.MissingPermissions):
        try:
            await ctx.author.send("❌ You need the **Manage Messages** permission to use `!echo`.")
        except discord.Forbidden:
            pass

# --- Run Web Server and Bot ---
def start_web():
    import uvicorn
    uvicorn.run(web.app, host="0.0.0.0", port=3000)

if __name__ == "__main__":
    threading.Thread(target=start_web).start()
    bot.run(TOKEN)
