import os
import re
import threading
import logging
from typing import Optional, List
import discord
from discord.ext import commands
from discord import app_commands, Interaction, Embed, Webhook
import web  # FastAPI web server file
from datetime import timedelta, datetime
import aiohttp

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Environment variables with validation
TOKEN = os.environ.get("DISCORD_TOKEN")
if not TOKEN:
    raise ValueError("DISCORD_TOKEN environment variable is required")

LOG_CHANNEL_ID = int(os.environ.get("LOG_CHANNEL_ID", 0)) or None
GUILD_ID = int(os.environ.get("GUILD_ID", 0)) or None
APPLICATION_ID = os.environ.get("APPLICATION_ID")

# Bot configuration
intents = discord.Intents.default()
intents.message_content = True
intents.members = True
intents.guilds = True

class ModeratedBot(commands.Bot):
    """Custom bot class with enhanced functionality."""
    
    def __init__(self):
        super().__init__(
            command_prefix="/",
            intents=intents,
            application_id=APPLICATION_ID
        )
        self.setup_automod_patterns()
        
    def setup_automod_patterns(self):
        """Initialize regex patterns for automod."""
        raw_patterns = [
            # N slur
            r"n[\W_]*[i1l!|][\W_]*[gq9][\W_]*[gq9][\W_]*[e3a@r4][\W_]*[r4]?",
            # R slur
            r"r[\W_]*[e3][\W_]*[t7][\W_]*[a@][\W_]*[r4][\W_]*[d]+(?:[\W_]*[e3][\W_]*[d])?",
            # F Slur - Faggot
            r"f[\W_]*[a@4][\W_]*[gq69]{2,}[\W_]*[o0][\W_]*[t+]+",
            # F Slur - Fag
            r"\bf[\W_]{0,2}[a@4][\W_]{0,2}[gq69]\b",
            # T Slur
            r"t[\W_]*[r][\W_]*[a@4][\W_]*[n]+[\W_]*[n]+[\W_]*[yi3e]+"
        ]
        self.regex_patterns = [
            re.compile(pattern, re.IGNORECASE) 
            for pattern in raw_patterns
        ]
        
    def has_forbidden_content(self, text: str) -> bool:
        """Check if text contains forbidden content."""
        return any(pattern.search(text) for pattern in self.regex_patterns)

bot = ModeratedBot()

class CommandLogger:
    """Handles command logging functionality."""
    
    @staticmethod
    async def log_command(
        user: discord.User,
        command_name: str,
        parameters: dict,
        success: bool,
        is_slash: bool,
        error_message: Optional[str] = None
    ):
        """Log command usage to the designated channel."""
        if not LOG_CHANNEL_ID:
            return

        try:
            log_channel = await bot.fetch_channel(LOG_CHANNEL_ID)
            embed = Embed(
                title="Command Executed",
                color=discord.Color.green() if success else discord.Color.red(),
                timestamp=datetime.utcnow()
            )
            
            embed.add_field(
                name="User", 
                value=f"{user.display_name} ({user.id})", 
                inline=False
            )
            embed.add_field(name="Command", value=command_name, inline=True)
            embed.add_field(
                name="Type", 
                value="Slash Command" if is_slash else "Text Command", 
                inline=True
            )
            embed.add_field(
                name="Parameters", 
                value=str(parameters) if parameters else "None", 
                inline=False
            )
            embed.add_field(
                name="Status", 
                value="✅ Success" if success else "❌ Failed", 
                inline=True
            )
            
            if error_message:
                embed.add_field(name="Error", value=error_message, inline=False)
                
            await log_channel.send(embed=embed)
            
        except Exception as e:
            logger.error(f"Failed to log command usage: {e}")

class AutoModerator:
    """Handles automatic moderation functionality."""
    
    @staticmethod
    async def handle_violation(message: discord.Message):
        """Handle automod violation with multiple actions."""
        actions_taken = {
            "message_deleted": False,
            "user_notified": False,
            "user_timed_out": False
        }
        
        # Try to notify user
        try:
            await message.reply(
                "⚠️ Your message contains prohibited content and has been removed.",
                delete_after=10
            )
            actions_taken["user_notified"] = True
        except discord.HTTPException as e:
            logger.warning(f"Failed to notify user: {e}")
        
        # Try to delete message
        try:
            await message.delete()
            actions_taken["message_deleted"] = True
        except discord.HTTPException as e:
            logger.warning(f"Failed to delete message: {e}")
        
        # Try to timeout user (if bot has permissions)
        try:
            if (message.guild and 
                message.guild.me.guild_permissions.moderate_members and
                not message.author.guild_permissions.administrator):
                
                timeout_until = datetime.utcnow() + timedelta(minutes=5)
                await message.author.timeout(
                    timeout_until, 
                    reason="Automatic moderation: prohibited content"
                )
                actions_taken["user_timed_out"] = True
                
        except discord.HTTPException as e:
            logger.warning(f"Failed to timeout user: {e}")
        
        # Log the incident
        await AutoModerator.log_incident(message, actions_taken)
    
    @staticmethod
    async def log_incident(message: discord.Message, actions: dict):
        """Log automod incident to the log channel."""
        if not LOG_CHANNEL_ID:
            return
            
        try:
            log_channel = await bot.fetch_channel(LOG_CHANNEL_ID)
            embed = Embed(
                title="🛡️ AutoMod Action Taken",
                color=discord.Color.orange(),
                timestamp=datetime.utcnow()
            )
            
            embed.add_field(
                name="User", 
                value=f"{message.author.display_name} ({message.author.id})", 
                inline=False
            )
            embed.add_field(
                name="Channel", 
                value=message.channel.mention, 
                inline=True
            )
            embed.add_field(
                name="Message Content", 
                value=f"```{message.content[:500]}```" if message.content else "No content", 
                inline=False
            )
            
            # Add action results
            for action, success in actions.items():
                embed.add_field(
                    name=action.replace("_", " ").title(),
                    value="✅" if success else "❌",
                    inline=True
                )
            
            embed.set_footer(
                text=f"Message ID: {message.id}",
                icon_url=message.author.display_avatar.url
            )
            
            await log_channel.send(embed=embed)
            
        except Exception as e:
            logger.error(f"Failed to log automod incident: {e}")

def create_help_embed() -> Embed:
    """Create the help command embed."""
    embed = Embed(
        title="🤖 Bot Commands",
        description="Here are the available commands:",
        color=discord.Color.blurple()
    )
    
    embed.add_field(
        name="/echo",
        value="Make the bot send a message\n*Requires: Manage Messages permission*",
        inline=False
    )
    embed.add_field(
        name="/help",
        value="Display this help message",
        inline=False
    )
    embed.add_field(
        name="/officer-echo",
        value="Make an officer (webhook) send a message\n*Requires: Manage Messages permission*",
        inline=False
    )
    
    embed.set_footer(text="Use slash commands by typing / followed by the command name")
    return embed

# --- Bot Events ---
@bot.event
async def on_ready():
    """Bot startup event."""
    logger.info(f"Bot logged in as {bot.user} (ID: {bot.user.id})")
    
    # Sync slash commands
    if GUILD_ID:
        try:
            guild = discord.Object(id=GUILD_ID)
            synced = await bot.tree.sync(guild=guild)
            logger.info(f"Synced {len(synced)} command(s) to guild {GUILD_ID}")
        except Exception as e:
            logger.error(f"Failed to sync commands to guild: {e}")
    else:
        try:
            synced = await bot.tree.sync()
            logger.info(f"Synced {len(synced)} global command(s)")
        except Exception as e:
            logger.error(f"Failed to sync global commands: {e}")

@bot.event
async def on_message(message: discord.Message):
    """Handle incoming messages for automod."""
    # Ignore bot messages
    if message.author.bot:
        return
    
    # Don't process slash commands or app commands
    if message.content.startswith('/'):
        return
    
    # Check for forbidden content
    if bot.has_forbidden_content(message.content):
        await AutoModerator.handle_violation(message)

# --- Slash Commands ---
@bot.tree.command(
    name="help",
    description="Show available bot commands",
    guild=discord.Object(id=GUILD_ID) if GUILD_ID else None
)
async def help_command(interaction: Interaction):
    """Display help information."""
    embed = create_help_embed()
    
    try:
        await interaction.response.send_message(embed=embed, ephemeral=True)
        await CommandLogger.log_command(
            interaction.user, "help", {}, True, True
        )
    except Exception as e:
        logger.error(f"Help command failed: {e}")
        await CommandLogger.log_command(
            interaction.user, "help", {}, False, True, str(e)
        )

@bot.tree.command(
    name="echo",
    description="Make the bot send a message",
    guild=discord.Object(id=GUILD_ID) if GUILD_ID else None
)
@app_commands.describe(
    message="The message content to send",
    channel="Target channel (optional, defaults to current channel)"
)
async def echo_command(
    interaction: Interaction,
    message: str,
    channel: Optional[discord.TextChannel] = None
):
    """Echo a message to a specified channel."""
    params = {
        "message": message,
        "channel": channel.name if channel else "current"
    }
    
    # Check permissions
    if not interaction.user.guild_permissions.manage_messages:
        embed = Embed(
            title="❌ Permission Denied",
            description="You need the **Manage Messages** permission to use this command.",
            color=discord.Color.red()
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)
        await CommandLogger.log_command(
            interaction.user, "echo", params, False, True, "Insufficient permissions"
        )
        return
    

    
    try:
        target_channel = channel or interaction.channel
        
        # Respond to interaction first
        embed = Embed(
            title="✅ Message Sent",
            description=f"Your message has been sent to {target_channel.mention}",
            color=discord.Color.green()
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)
        
        # Then send the actual message
        await target_channel.send(message)
        
        await CommandLogger.log_command(
            interaction.user, "echo", params, True, True
        )
        
    except discord.HTTPException as e:
        error_msg = f"Failed to send message: {str(e)}"
        embed = Embed(
            title="❌ Send Failed",
            description="There was an error sending your message.",
            color=discord.Color.red()
        )
        
        # Check if we haven't responded to the interaction yet
        if not interaction.response.is_done():
            await interaction.response.send_message(embed=embed, ephemeral=True)
        else:
            await interaction.followup.send(embed=embed, ephemeral=True)
            
        await CommandLogger.log_command(
            interaction.user, "echo", params, False, True, error_msg
        )

# Map officer names to their corresponding Render env variable names
OFFICER_ENV_KEYS = {
    "Boykisser - Gay General": "BOYKISSER_OFFICER_GAYGENERAL",
    "Boykisser - Boykisser-3": "BOYKISSER_OFFICER_BOYKISSER3",
    "Boykisser - Furry's Talking Corner": "BOYKISSER_OFFICER_FURRYSTALKINGCORNER",
}

@bot.tree.command(
    name="officer-echo",
    description="Send a message as an officer (via webhook)",
    guild=discord.Object(id=GUILD_ID) if GUILD_ID else None
)
@app_commands.describe(
    officer="The officer identity to use (via webhook)",
    message="The message content to send"
)
@app_commands.choices(
    officer=[
        app_commands.Choice(name=name, value=name)
        for name in OFFICER_ENV_KEYS.keys()
    ]
)
async def officer_echo_command(
    interaction: Interaction,
    officer: app_commands.Choice[str],
    message: str
):
    params = {
        "officer": officer.name,
        "message": message
    }

    if not interaction.user.guild_permissions.manage_messages:
        embed = Embed(
            title="❌ Permission Denied",
            description="You need the **Manage Messages** permission to use this command.",
            color=discord.Color.red()
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)
        await CommandLogger.log_command(
            interaction.user, "officer-echo", params, False, True, "Insufficient permissions"
        )
        return

    env_key = OFFICER_ENV_KEYS.get(officer.name)
    webhook_url = os.getenv(env_key)

    if not webhook_url:
        embed = Embed(
            title="❌ Webhook Missing",
            description=f"Environment variable `{env_key}` not set.",
            color=discord.Color.red()
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)
        await CommandLogger.log_command(
            interaction.user, "officer-echo", params, False, True, f"Missing env var: {env_key}"
        )
        return

    try:
        async with aiohttp.ClientSession() as session:
            webhook = Webhook.from_url(webhook_url, session=session)
            await webhook.send(content=message)

        embed = Embed(
            title="✅ Officer Message Sent",
            description=f"Message sent as **{officer.name}**",
            color=discord.Color.green()
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)

        await CommandLogger.log_command(
            interaction.user, "officer-echo", params, True, True
        )

    except discord.HTTPException as e:
        error_msg = f"Failed to send message via webhook: {str(e)}"
        embed = Embed(
            title="❌ Send Failed",
            description="An error occurred while sending the message.",
            color=discord.Color.red()
        )
        if not interaction.response.is_done():
            await interaction.response.send_message(embed=embed, ephemeral=True)
        else:
            await interaction.followup.send(embed=embed, ephemeral=True)

        await CommandLogger.log_command(
            interaction.user, "officer-echo", params, False, True, error_msg
        )


def start_web_server():
    """Start the web server in a separate thread."""
    try:
        import uvicorn
        uvicorn.run(web.app, host="0.0.0.0", port=3000, log_level="info")
    except Exception as e:
        logger.error(f"Failed to start web server: {e}")

def main():
    """Main function to start the bot and web server."""
    # Start web server in background thread
    web_thread = threading.Thread(target=start_web_server, daemon=True)
    web_thread.start()
    logger.info("Web server thread started")
    
    # Start the bot
    try:
        bot.run(TOKEN)
    except Exception as e:
        logger.error(f"Bot failed to start: {e}")
        raise

if __name__ == "__main__":
    main()
