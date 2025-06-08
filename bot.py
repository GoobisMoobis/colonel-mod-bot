import os
import re
import threading
import discord
from discord.ext import commands
from discord import app_commands, Interaction, Embed
import web  # FastAPI web server file
from datetime import timedelta, datetime

TOKEN = os.environ.get("DISCORD_TOKEN")
LOG_CHANNEL_ID = int(os.environ.get("LOG_CHANNEL_ID", 0))
GUILD_ID = int(os.environ.get("GUILD_ID", 0)) or None

intents = discord.Intents.default()
intents.message_content = True
intents.members = True
intents.guilds = True

class CustomBot(commands.Bot):
    def __init__(self):
        super().__init__(command_prefix="!", intents=intents, application_id=os.environ.get("APPLICATION_ID"))

bot = CustomBot()
tree = bot.tree

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
    embed.add_field(name="/echo [message] (channel)", value="Make the bot say something. Channel is optional. Requires Manage Messages.", inline=False)
    embed.add_field(name="/help", value="Shows this help message.", inline=False)
    return embed

# --- Logging Function ---
async def log_command(ctx_user, name, params, success: bool, is_slash: bool, reason: str = None):
    if not LOG_CHANNEL_ID:
        return

    try:
        log_channel = await bot.fetch_channel(LOG_CHANNEL_ID)
        embed = Embed(
            title="Command Used",
            color=discord.Color.green() if success else discord.Color.red(),
            timestamp=datetime.utcnow()
        )
        embed.add_field(name="User", value=f"{ctx_user} ({ctx_user.id})", inline=False)
        embed.add_field(name="Command", value=name, inline=True)
        embed.add_field(name="Type", value="Slash Command" if is_slash else "Text Command", inline=True)
        embed.add_field(name="Parameters", value=str(params), inline=False)
        embed.add_field(name="Success", value="✅" if success else "❌", inline=True)
        if reason:
            embed.add_field(name="Info", value=reason, inline=False)
        await log_channel.send(embed=embed)
    except Exception as e:
        print("Failed to log command usage:", e)

# --- Events ---
@bot.event
async def on_ready():
    print(f"Logged in as {bot.user}")
    if GUILD_ID:
        try:
            synced = await tree.sync(guild=discord.Object(id=GUILD_ID))
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
            await message.author.timeout(datetime.utcnow() + timedelta(minutes=5), reason="AutoMod violation")
            member_timed_out = True
    except Exception:
        pass

    embed = discord.Embed(
        title="AutoMod triggered!",
        color=discord.Color.red(),
        timestamp=datetime.utcnow()
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

# --- /help Slash Command ---
@tree.command(name="help", description="Show the list of commands", guild=discord.Object(id=GUILD_ID))
async def slash_help(interaction: Interaction):
    embed = get_help_embed()
    try:
        await interaction.response.send_message(embed=embed, ephemeral=True)
        await log_command(interaction.user, "help", {}, True, True)
    except Exception as e:
        await log_command(interaction.user, "help", {}, False, True, str(e))

# --- /echo Slash Command ---
@tree.command(name="echo", description="Make the bot say something", guild=discord.Object(id=GUILD_ID))
@app_commands.describe(message="The message to send", channel="The channel to send it in (optional)")
async def slash_echo(interaction: Interaction, message: str, channel: discord.TextChannel = None):
    params = {"message": message, "channel": str(channel) if channel else "(current channel)"}

    if not interaction.user.guild_permissions.manage_messages:
        embed = discord.Embed(
            title="Permission Denied",
            description="You need the **Manage Messages** permission to use this command.",
            color=discord.Color.red()
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)
        await log_command(interaction.user, "echo", params, False, True, "Missing permission")
        return

    try:
        target_channel = channel or interaction.channel
        await target_channel.send(message)
        await interaction.response.send_message(f"✅ Sent in {target_channel.mention}", ephemeral=True)
        await log_command(interaction.user, "echo", params, True, True)
    except Exception as e:
        await log_command(interaction.user, "echo", params, False, True, str(e))

# --- Run Web Server and Bot ---
def start_web():
    import uvicorn
    uvicorn.run(web.app, host="0.0.0.0", port=3000)

if __name__ == "__main__":
    threading.Thread(target=start_web).start()
    bot.run(TOKEN)
