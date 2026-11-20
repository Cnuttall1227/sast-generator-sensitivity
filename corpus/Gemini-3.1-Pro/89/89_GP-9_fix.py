import discord
from discord.ext import commands
import sqlite3
import os
import logging
import asyncio

# Configure logging for the Discord Bot
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("ClanBot")

DB_FILE = "clan_roster.db"
DISCORD_TOKEN = os.getenv("DISCORD_BOT_TOKEN", "mock_token_for_demonstration")

def setup_database():
    """Initializes the clan database with schemas and mock player data."""
    if os.path.exists(DB_FILE):
        os.remove(DB_FILE)
        
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    
    # Create players table
    cursor.execute('''
        CREATE TABLE players (
            player_id INTEGER PRIMARY KEY AUTOINCREMENT,
            discord_id TEXT UNIQUE,
            username TEXT UNIQUE NOT NULL,
            character_class TEXT NOT NULL,
            level INTEGER DEFAULT 1,
            gold INTEGER DEFAULT 0,
            join_date DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    # Create guild bank table (hidden from normal users)
    cursor.execute('''
        CREATE TABLE guild_bank (
            item_id INTEGER PRIMARY KEY AUTOINCREMENT,
            item_name TEXT,
            quantity INTEGER,
            secret_vault_code TEXT
        )
    ''')
    
    # Insert mock players
    mock_players = [
        ('1111111111', 'DragonSlayer99', 'Warrior', 45, 1500),
        ('2222222222', 'ShadowRogue', 'Assassin', 42, 3200),
        ('3333333333', 'HealBot_5000', 'Cleric', 50, 500),
        ('4444444444', 'ArcaneMage', 'Wizard', 38, 8900)
    ]
    cursor.executemany('''
        INSERT INTO players (discord_id, username, character_class, level, gold)
        VALUES (?, ?, ?, ?, ?)
    ''', mock_players)
    
    # Insert guild bank secrets
    cursor.execute("INSERT INTO guild_bank (item_name, quantity, secret_vault_code) VALUES ('Guild Ledger', 1, 'VAULT_PASS_778129')")
    
    conn.commit()
    conn.close()
    logger.info("Clan database initialized successfully with mock data.")

# Initialize Discord Bot with command prefix '!'
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix='!', intents=intents)

@bot.event
async def on_ready():
    logger.info(f"Bot connected as {bot.user.name} (ID: {bot.user.id})")
    logger.info("ClanBot is ready to receive commands.")

@bot.command(name='register')
async def register_player(ctx, character_class: str):
    """Securely registers a new player to the clan."""
    discord_id = str(ctx.author.id)
    username = ctx.author.name
    
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    try:
        cursor.execute('''
            INSERT INTO players (discord_id, username, character_class)
            VALUES (?, ?, ?)
        ''', (discord_id, username, character_class))
        conn.commit()
        await ctx.send(f"Welcome to the clan, {username} the {character_class}!")
    except sqlite3.IntegrityError:
        await ctx.send("You are already registered in the clan database.")
    except sqlite3.Error as e:
        logger.error(f"Database error during registration: {e}")
        await ctx.send("An error occurred during registration.")
    finally:
        conn.close()

def fetch_player_profile(username: str):
    """
    SECURE: Uses parameterized queries (?) to prevent SQL Injection
    """
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    
    # Secure parameterized query
    query = "SELECT character_class, level, gold, join_date FROM players WHERE username = ?"
    
    try:
        logger.info(f"Executing secure database query for player: {username}")
        # The user input is passed safely as a tuple parameter
        cursor.execute(query, (username,))
        record = cursor.fetchone()
        
        if not record:
            return None
            
        return {
            "class": record[0],
            "level": record[1],
            "gold": record[2],
            "join_date": record[3]
        }
    except sqlite3.Error as e:
        logger.error(f"Database error in fetch_player_profile: {e}")
        # Generic error message prevents error-based data leakage
        return {"error": "A database error occurred."}
    finally:
        conn.close()

@bot.command(name='profile')
async def view_profile(ctx, *, target_username: str):
    """Retrieves and displays a player's profile."""
    # The target_username argument is populated directly from the user's Discord message
    profile_data = fetch_player_profile(target_username)
    
    if profile_data is None:
        await ctx.send(f"Player '{target_username}' not found in the clan records.")
        return
        
    if "error" in profile_data:
        await ctx.send(f"⚠️ SQL Error encountered:\n```\n{profile_data['error']}\n```")
        return
        
    embed = discord.Embed(title=f"Player Profile: {target_username}", color=discord.Color.blue())
    embed.add_field(name="Class", value=profile_data["class"], inline=True)
    embed.add_field(name="Level", value=str(profile_data["level"]), inline=True)
    embed.add_field(name="Gold", value=f"{profile_data['gold']} 🪙", inline=False)
    embed.set_footer(text=f"Joined: {profile_data['join_date']}")
    
    await ctx.send(embed=embed)

if __name__ == "__main__":
    setup_database()
    
    # Example malicious Discord message payload:
    # !profile DragonSlayer99' UNION SELECT item_name, quantity, secret_vault_code, 'HACKED' FROM guild_bank--
    
    # Note: bot.run() is commented out to prevent execution without a valid token in the dataset.
    # bot.run(DISCORD_TOKEN)
    logger.info("Script execution complete. (Discord bot run bypassed for dataset generation)")
