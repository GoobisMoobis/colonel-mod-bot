import os
import re
import threading
import logging
from typing import Optional, List
import discord
from discord.ext import commands
from discord import app_commands, Interaction, Embed, ui
import web  # FastAPI web server file
from datetime import timedelta, datetime
import random
import glob

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
            command_prefix="!",
            intents=intents,
            application_id=APPLICATION_ID
        )
        self.setup_automod_patterns()
        self.active_restaurants = {}
        
    def setup_automod_patterns(self):
        """Initialize regex patterns for automod."""
        raw_patterns = [
            # N slur
            r"n[\W_]*[i1l!|][\W_]*[gq9][\W_]*[gq9][\W_]*[e3a@r4][\W_]*[r4]?",
            # R slur
            r"r[\W_]*[e3][\W_]*[t7][\W_]*[a@][\W_]*[r4][\W_]*[d]+(?:[\W_]*[e3][\W_]*[d])?"
        ]
        self.regex_patterns = [
            re.compile(pattern, re.IGNORECASE) 
            for pattern in raw_patterns
        ]
        
    def has_forbidden_content(self, text: str) -> bool:
        """Check if text contains forbidden content."""
        return any(pattern.search(text) for pattern in self.regex_patterns)
    
    def get_random_waiter(self) -> tuple[str, str]:
        """Get a random waiter name and image path from assets/waiters folder."""
        try:
            # Get all image files from assets/waiters directory
            waiter_files = glob.glob("./assets/waiters/*")
            waiter_files = [f for f in waiter_files if f.lower().endswith(('.png', '.jpg', '.jpeg', '.gif', '.webp'))]
            
            if not waiter_files:
                # Fallback if no waiter images found
                return "Generic Waiter", None
            
            # Select random waiter file
            selected_file = random.choice(waiter_files)
            
            # Extract waiter name from filename (without extension)
            waiter_name = os.path.splitext(os.path.basename(selected_file))[0]
            
            return waiter_name, selected_file
            
        except Exception as e:
            logger.warning(f"Failed to get random waiter: {e}")
            return "Generic Waiter", None

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

# --- Restaurant Command UI Classes ---
class RestaurantViewStep1(ui.View):
    def __init__(self, user_id: int):
        super().__init__(timeout=300)  # Increased timeout to 5 minutes
        self.user_id = user_id
        self.waiter_name, self.waiter_image = bot.get_random_waiter()

    @ui.button(label="Get Seated", style=discord.ButtonStyle.primary, emoji="🪑")
    async def get_seated(self, interaction: Interaction, button: ui.Button):
        if interaction.user.id != self.user_id:
            return await interaction.response.send_message("This isn't your session!", ephemeral=True)
        await self.next_step(interaction)

    @ui.button(label="Request Different Waiter", style=discord.ButtonStyle.secondary, emoji="🔄")
    async def request_different_waiter(self, interaction: Interaction, button: ui.Button):
        if interaction.user.id != self.user_id:
            return await interaction.response.send_message("This isn't your session!", ephemeral=True)
        
        # Get a new random waiter
        self.waiter_name, self.waiter_image = bot.get_random_waiter()
        
        # Update the embed with new waiter info
        embed = Embed(
            title="👋 Welcome to Femboy Hooters!",
            description=f"Your waiter **{self.waiter_name}** is ready to serve you!\nWould you like to be seated or request a different waiter?",
            color=discord.Color.blurple()
        )
        
        # Add waiter image if available
        if self.waiter_image:
            try:
                file = discord.File(self.waiter_image, filename="waiter.png")
                embed.set_thumbnail(url="attachment://waiter.png")
                await interaction.response.edit_message(embed=embed, view=self, attachments=[file])
            except Exception as e:
                logger.warning(f"Failed to attach waiter image: {e}")
                await interaction.response.edit_message(embed=embed, view=self)
        else:
            await interaction.response.edit_message(embed=embed, view=self)

    async def next_step(self, interaction: Interaction):
        try:
            # Create the menu embed and view immediately
            menu_embed = Embed(
                title="📜 Menu - You've been seated!",
                description=f"Your waiter **{self.waiter_name}** has seated you at a table.\nPlease select a dish from our delicious options:",
                color=discord.Color.green()
            )
            menu_embed.add_field(
                name="Available Dishes",
                value="🍝 Spaghetti - Classic Italian pasta\n🍔 Burger - Juicy beef burger\n🍣 Sushi - Fresh Japanese sushi",
                inline=False
            )
            
            # Add waiter image if available
            if self.waiter_image:
                try:
                    file = discord.File(self.waiter_image, filename="waiter.png")
                    menu_embed.set_thumbnail(url="attachment://waiter.png")
                except Exception as e:
                    logger.warning(f"Failed to prepare waiter image: {e}")
                    file = None
            else:
                file = None
            
            # Create the menu view
            view = RestaurantViewStep2(self.user_id)
            
            # Update the message with the menu and dropdown in one go
            if file:
                await interaction.response.edit_message(embed=menu_embed, view=view, attachments=[file])
            else:
                await interaction.response.edit_message(embed=menu_embed, view=view)
            
        except Exception as e:
            logger.error(f"Error in next_step: {e}")
            # Fallback error handling
            try:
                error_embed = Embed(
                    title="❌ Service Error",
                    description="Something went wrong while seating you. Please try the command again!",
                    color=discord.Color.red()
                )
                
                if not interaction.response.is_done():
                    await interaction.response.edit_message(embed=error_embed, view=None)
                else:
                    # This shouldn't happen, but just in case
                    await interaction.followup.edit_message(interaction.message.id, embed=error_embed, view=None)
                
                # Clean up active session on error
                bot.active_restaurants.pop(self.user_id, None)
            except Exception as cleanup_error:
                logger.error(f"Error during cleanup: {cleanup_error}")

class RestaurantViewStep2(ui.View):
    def __init__(self, user_id: int):
        super().__init__(timeout=300)  # Increased timeout to 5 minutes
        self.user_id = user_id
        self.add_item(RestaurantDropdown(user_id))
    
    async def on_timeout(self):
        """Handle view timeout"""
        try:
            # Clean up active session when view times out
            bot.active_restaurants.pop(self.user_id, None)
            logger.info(f"Restaurant session timed out for user {self.user_id}")
        except Exception as e:
            logger.error(f"Error handling timeout: {e}")

class RestaurantDropdown(ui.Select):
    def __init__(self, user_id: int):
        self.user_id = user_id
        options = [
            discord.SelectOption(
                label="Spaghetti", 
                value="spaghetti", 
                emoji="🍝",
                description="Classic Italian pasta with marinara sauce"
            ),
            discord.SelectOption(
                label="Burger", 
                value="burger", 
                emoji="🍔",
                description="Juicy beef burger with all the fixings"
            ),
            discord.SelectOption(
                label="Sushi", 
                value="sushi", 
                emoji="🍣",
                description="Fresh Japanese sushi rolls"
            )
        ]
        super().__init__(placeholder="Choose your dish...", options=options)

    async def callback(self, interaction: Interaction):
        if interaction.user.id != self.user_id:
            return await interaction.response.send_message("This isn't your session!", ephemeral=True)
        
        try:
            food = self.values[0]
            food_emojis = {"spaghetti": "🍝", "burger": "🍔", "sushi": "🍣"}
            
            # Show preparation message
            await interaction.response.send_message(embed=Embed(
                title="⏳ Please wait...",
                description=f"Your {food_emojis.get(food, '🍽️')} {food} is being prepared by our talented kitchen staff...",
                color=discord.Color.orange()
            ))
            
            # Wait for "preparation time"
            await asyncio.sleep(5)
            
            # Serve the food
            await interaction.followup.send(embed=Embed(
                title="✅ Enjoy your meal!",
                description=f"Here's your delicious **{food_emojis.get(food, '🍽️')} {food}**!\n\nBon appétit! Thanks for dining at Femboy Hooters!",
                color=discord.Color.green()
            ))
            
            # Clean up active session
            bot.active_restaurants.pop(interaction.user.id, None)
            
        except Exception as e:
            logger.error(f"Error in dropdown callback: {e}")
            try:
                if not interaction.response.is_done():
                    await interaction.response.send_message(
                        "❌ Sorry, there was an issue with your order. Please try again!",
                        ephemeral=True
                    )
                else:
                    await interaction.followup.send(
                        "❌ Sorry, there was an issue with your order. Please try again!",
                        ephemeral=True
                    )
                # Clean up active session on error
                bot.active_restaurants.pop(self.user_id, None)
            except Exception as cleanup_error:
                logger.error(f"Error during dropdown cleanup: {cleanup_error}")

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
        name="/femboy-hooters",
        value="i hate myself",
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
    
    # Process prefix commands (if any)
    await bot.process_commands(message)

@bot.event
async def on_command_error(ctx, error):
    """Handle command errors."""
    logger.error(f"Command error in {ctx.command}: {error}")

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

@bot.tree.command(
    name="femboy-hooters", 
    description="I hate myself",
    guild=discord.Object(id=GUILD_ID) if GUILD_ID else None
)
async def restaurant(interaction: Interaction):
    """Interactive restaurant experience command."""
    user_id = interaction.user.id
    
    # Check if user already has an active restaurant session
    if user_id in bot.active_restaurants:
        embed = Embed(
            title="❌ Active Session",
            description="You are already at femboy hooters!",
            color=discord.Color.red()
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)
        await CommandLogger.log_command(
            interaction.user, "femboy-hooters", {}, False, True, "Active session exists"
        )
        return

    try:
        # Mark user as having an active session
        bot.active_restaurants[user_id] = True
        
        # Get initial random waiter
        view = RestaurantViewStep1(user_id)
        
        embed = Embed(
            title="👋 Welcome to Femboy Hooters!",
            description=f"Your waiter **{view.waiter_name}** is ready to serve you!\nWould you like to be seated or request a different waiter?",
            color=discord.Color.blurple()
        )
        
        # Add waiter image if available
        if view.waiter_image:
            try:
                file = discord.File(view.waiter_image, filename="waiter.png")
                embed.set_thumbnail(url="attachment://waiter.png")
                await interaction.response.send_message(
                    embed=embed, 
                    view=view, 
                    file=file,
                )
            except Exception as e:
                logger.warning(f"Failed to attach waiter image: {e}")
                await interaction.response.send_message(
                    embed=embed, 
                    view=view, 
                    ephemeral=True
                )
        else:
            await interaction.response.send_message(
                embed=embed, 
                view=view, 
            )
        
        await CommandLogger.log_command(
            interaction.user, "femboy-hooters", {"waiter": view.waiter_name}, True, True
        )
        
    except Exception as e:
        logger.error(f"Femboy-hooters command failed: {e}")
        # Clean up active session on error
        bot.active_restaurants.pop(user_id, None)
        
        embed = Embed(
            title="❌ Restaurant Unavailable",
            description="Sorry, Femboy Hooters doesn't have any seating availible right now. Please come back again later.",
            color=discord.Color.red()
        )
        
        if not interaction.response.is_done():
            await interaction.response.send_message(embed=embed, ephemeral=True)
        else:
            await interaction.followup.send(embed=embed, ephemeral=True)
            
        await CommandLogger.log_command(
            interaction.user, "femboy-hooters", {}, False, True, str(e)
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
