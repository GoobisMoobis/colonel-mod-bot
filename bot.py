import os
import re
import threading
import discord
from discord import app_commands, Interaction, Embed
import web  # FastAPI server

TOKEN = os.environ.get("DISCORD_TOKEN")
LOG_CHANNEL_ID = int(os.environ.get("LOG_CHANNEL_ID", 0))
GUILD_ID = int(os.environ.get("GUILD_ID", 0)) or None

intents = discord.Intents.default()
intents.message_content = True
intents.members = True
intents.guilds = True

bot = discord.Client(intents=intents)
tree = bot.tree

# --- Regex filters ---
raw_patterns = [
    r"badword1",
    r"\bforbidden\b",
    r"somepattern\d+"
]
regex_list = [re.compile(pat, re.IGNORECASE) for pat in raw_patterns]

# --- Logging helper ---
async def log_command_use(user, channel, command_name, command_type, success, args=None, error=None):
    embed = discord.Embed(
        title="Command Used",
        color=discord.Color.green() if success else discord.Color.red(),
        timestamp=discord.utils.utcnow()
    )
    embed.add_field(name="Command", value=command_name, inline=True)
    embed.add_field(name="Type", value=command_type, inline=True)
    embed.add_field(name="Used By", value=f"{user} ({user.id})", inline=False)
    embed.add_field(name="Channel", value=f"{channel.mention} ({channel.id})", inline=False)
    if args:
        embed.add_field(name="Arguments", value=args, inline=False)
    if not success and error:
        embed.add_field(name="Error", value=error, inline=False)

    embed.set_footer(text="Command Log", icon_url=user.display_avatar.url)
    try:
        log_channel = await bot.fetch_channel(LOG_CHANNEL_ID)
        await log_channel.send(embed=embed)
    except Exception as e:
        print(f"Failed to log command: {e}")

# --- Bot Ready ---
@bot.event
async def on_ready():
    print(f"Logged in as {bot.user}")
    if GUILD_ID:
        try:
            synced = await bot.tree.sync(guild=discord.Object(id=GUILD_ID))
            print(f"Synced {len(synced)} commands to guild {GUILD_ID}")
        except Exception as e:
            print(f"Failed to sync slash commands: {e}")

# --- Regex Automod ---
@bot.event
async def on_message(message: discord.Message):
    if message.author.bot:
        return

    if not any(r.search(message.content) for r in regex_list):
        return

    message_deleted = False
    member_notified = False
    member_timed_out = False

    try:
        await message.reply("This word is not allowed here")
        member_notified = True
    except:
        pass

    try:
        await message.delete()
        message_deleted = True
    except:
        pass

    try:
        if message.guild.me.guild_permissions.moderate_members:
            await message.author.timeout(discord.utils.utcnow() + discord.timedelta(minutes=5), reason="AutoMod")
            member_timed_out = True
    except:
        pass

    embed = discord.Embed(
        title="AutoMod Triggered",
        color=discord.Color.red(),
        timestamp=discord.utils.utcnow()
    )
    embed.add_field(name="Message Deleted", value="✅" if message_deleted else "❌")
    embed.add_field(name="User Notified", value="✅" if member_notified else "❌")
    embed.add_field(name="User Timed Out", value="✅" if member_timed_out else "❌")
    embed.set_footer(text=str(message.author), icon_url=message.author.display_avatar.url)

    try:
        log_channel = await bot.fetch_channel(LOG_CHANNEL_ID)
        await log_channel.send(embed=embed)
    except Exception as e:
        print("Logging failed:", e)

    await bot.process_commands(message)

# --- Help Embed Generator ---
def get_help_embed() -> Embed:
    embed = Embed(title="Bot Commands Help", color=discord.Color.blurple())
    embed.add_field(name="/echo [message] (channel)", value="Make the bot say something.", inline=False)
    embed.add_field(name="/help", value="Show this help message", inline=False)
    return embed

# --- /help Command ---
@tree.command(name="help", description="Show help", guild=discord.Object(id=GUILD_ID))
async def slash_help(interaction: Interaction):
    await interaction.response.defer(thinking=False, ephemeral=True)
    embed = get_help_embed()
    await interaction.followup.send(embed=embed, ephemeral=True)
    await log_command_use(interaction.user, interaction.channel, "help", "Slash", True)

# --- /echo Command ---
@tree.command(name="echo", description="Make the bot say something", guild=discord.Object(id=GUILD_ID))
@app_commands.describe(message="Message to send", channel="Channel to send it in")
async def slash_echo(interaction: Interaction, message: str, channel: discord.TextChannel = None):
    await interaction.response.defer(ephemeral=True)
    if not interaction.user.guild_permissions.manage_messages:
        embed = Embed(title="Permission Denied", description="You need **Manage Messages**", color=discord.Color.red())
        await interaction.followup.send(embed=embed, ephemeral=True)
        await log_command_use(interaction.user, interaction.channel, "echo", "Slash", False, f"message={message}", "Missing Permissions")
        return

    target = channel or interaction.channel
    await target.send(message)
    await interaction.followup.send(f"✅ Sent in {target.mention}", ephemeral=True)
    await log_command_use(interaction.user, interaction.channel, "echo", "Slash", True, f"message={message}, channel={target.name}")

# --- Web + Bot Launch ---
def start_web():
    import uvicorn
    uvicorn.run(web.app, host="0.0.0.0", port=3000)

if __name__ == "__main__":
    threading.Thread(target=start_web).start()
    bot.run(TOKEN)
