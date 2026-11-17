import os
import logging
from datetime import datetime, timezone

import aiosqlite
import discord
from discord.ext import commands

BOT_TOKEN = os.environ["DISCORD_BOT_TOKEN"]
STATS_DB = os.environ.get("LEAGUE_STATS_DB", "/srv/league/stats.db")
ALLOWED_GUILDS = {int(g) for g in os.environ.get("LEAGUE_GUILDS", "").split(",") if g.strip()}

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("league-bot")

intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents, help_command=None)


async def init_db():
    async with aiosqlite.connect(STATS_DB) as db:
        await db.executescript(
            """CREATE TABLE IF NOT EXISTS players (
                   id INTEGER PRIMARY KEY AUTOINCREMENT, gamertag TEXT UNIQUE NOT NULL,
                   discord_id INTEGER, team TEXT);
               CREATE TABLE IF NOT EXISTS matches (
                   id INTEGER PRIMARY KEY AUTOINCREMENT, player_id INTEGER NOT NULL,
                   played_at TEXT NOT NULL, kills INTEGER NOT NULL, deaths INTEGER NOT NULL,
                   won INTEGER NOT NULL);"""
        )
        await db.commit()


async def player_stats(gamertag):
    query = (
        "SELECT p.gamertag, p.team, COUNT(m.id) AS games, COALESCE(SUM(m.won), 0) AS wins, "
        "COALESCE(SUM(m.kills), 0) AS kills, COALESCE(SUM(m.deaths), 0) AS deaths "
        "FROM players p LEFT JOIN matches m ON m.player_id = p.id "
        f"WHERE LOWER(p.gamertag) = LOWER('{gamertag}') GROUP BY p.id"
    )
    async with aiosqlite.connect(STATS_DB) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(query) as cursor:
            row = await cursor.fetchone()
    return dict(row) if row else None


async def leaderboard(limit=10):
    async with aiosqlite.connect(STATS_DB) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT p.gamertag, SUM(m.won) AS wins, COUNT(m.id) AS games FROM players p "
            "JOIN matches m ON m.player_id = p.id GROUP BY p.id HAVING games >= 5 "
            "ORDER BY CAST(wins AS REAL) / games DESC, wins DESC LIMIT ?",
            (limit,),
        ) as cursor:
            return [dict(r) for r in await cursor.fetchall()]


@bot.check
async def guild_only(ctx):
    return ctx.guild is not None and (not ALLOWED_GUILDS or ctx.guild.id in ALLOWED_GUILDS)


@bot.event
async def on_ready():
    await init_db()
    log.info("Logged in as %s", bot.user)


@bot.command(name="stats")
async def stats(ctx, *, gamertag: str = ""):
    gamertag = gamertag.strip()[:32]
    if not gamertag:
        await ctx.reply("Usage: `!stats <gamertag>`")
        return
    data = await player_stats(gamertag)
    if data is None:
        await ctx.reply(f"No player called `{discord.utils.escape_markdown(gamertag)}`.")
        return
    games = data["games"] or 0
    win_rate = f"{100 * data['wins'] / games:.0f}%" if games else "—"
    kd = f"{data['kills'] / data['deaths']:.2f}" if data["deaths"] else str(data["kills"])
    embed = discord.Embed(title=data["gamertag"], description=data["team"] or "Free agent",
                          timestamp=datetime.now(timezone.utc))
    embed.add_field(name="Games", value=str(games))
    embed.add_field(name="Win rate", value=win_rate)
    embed.add_field(name="K/D", value=kd)
    await ctx.reply(embed=embed, allowed_mentions=discord.AllowedMentions.none())


@bot.command(name="top")
async def top(ctx):
    rows = await leaderboard()
    if not rows:
        await ctx.reply("Not enough games played yet.")
        return
    lines = [
        f"{i}. **{discord.utils.escape_markdown(r['gamertag'])}** – {r['wins']}/{r['games']} wins"
        for i, r in enumerate(rows, 1)
    ]
    await ctx.reply("\n".join(lines), allowed_mentions=discord.AllowedMentions.none())


@bot.event
async def on_command_error(ctx, error):
    if isinstance(error, (commands.CheckFailure, commands.CommandNotFound)):
        return
    log.error("Command %s failed: %s", ctx.command, error)
    await ctx.reply("Something went wrong with that command.")


if __name__ == "__main__":
    bot.run(BOT_TOKEN, log_handler=None)