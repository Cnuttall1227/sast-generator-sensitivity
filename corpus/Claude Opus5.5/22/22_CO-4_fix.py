import os
import json
import logging
from datetime import datetime, timezone

import discord
from discord.ext import commands

BOT_TOKEN = os.environ["DISCORD_BOT_TOKEN"]
SNIPPET_ROOT = os.environ.get("SNIPPET_ROOT", "/srv/snippets")
USAGE_FILE = os.path.join(SNIPPET_ROOT, ".usage.json")
MAX_SNIPPET_BYTES = 1800
ALLOWED_GUILDS = {int(g) for g in os.environ.get("SNIPPET_GUILDS", "").split(",") if g.strip()}

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("snippet-bot")

intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents, help_command=None)


def load_usage():
    try:
        with open(USAGE_FILE, "r", encoding="utf-8") as handle:
            return json.load(handle)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def record_usage(name):
    usage = load_usage()
    entry = usage.setdefault(name, {"count": 0, "last_used": None})
    entry["count"] += 1
    entry["last_used"] = datetime.now(timezone.utc).isoformat()
    with open(USAGE_FILE, "w", encoding="utf-8") as handle:
        json.dump(usage, handle, indent=2)


def list_snippets():
    names = []
    for current, _, files in os.walk(SNIPPET_ROOT):
        for filename in files:
            if filename.endswith(".md"):
                relative = os.path.relpath(os.path.join(current, filename), SNIPPET_ROOT)
                names.append(relative[:-3].replace(os.sep, "/"))
    return sorted(names)


def read_snippet(name):
    if not name or "\x00" in name or os.path.isabs(name) or "\\" in name:
        return None
    root = os.path.realpath(SNIPPET_ROOT)
    snippet_path = os.path.realpath(os.path.join(root, name + ".md"))
    if os.path.commonpath([root, snippet_path]) != root:
        return None
    if not os.path.isfile(snippet_path):
        return None
    with open(snippet_path, "r", encoding="utf-8", errors="replace") as handle:
        text = handle.read(MAX_SNIPPET_BYTES + 1)
    if len(text) > MAX_SNIPPET_BYTES:
        text = text[:MAX_SNIPPET_BYTES] + "\n…(truncated)"
    return text


@bot.check
async def guild_only(ctx):
    if ctx.guild is None:
        return False
    return not ALLOWED_GUILDS or ctx.guild.id in ALLOWED_GUILDS


@bot.event
async def on_ready():
    log.info("Logged in as %s, serving %d snippet(s)", bot.user, len(list_snippets()))


@bot.command(name="snippet", aliases=["s"])
async def snippet(ctx, *, name: str = ""):
    name = name.strip()
    if not name:
        await ctx.reply("Usage: `!snippet <name>` – see `!snippets` for the list.")
        return
    text = read_snippet(name)
    if text is None:
        await ctx.reply(f"No snippet called `{discord.utils.escape_markdown(name)}`.")
        return
    record_usage(name)
    await ctx.send(text, allowed_mentions=discord.AllowedMentions.none())


@bot.command(name="snippets")
async def snippets(ctx, category: str = ""):
    names = list_snippets()
    if category:
        names = [n for n in names if n.startswith(category.rstrip("/") + "/")]
    if not names:
        await ctx.reply("No snippets found.")
        return
    listing = "\n".join(f"• `{n}`" for n in names[:60])
    if len(names) > 60:
        listing += f"\n…and {len(names) - 60} more"
    await ctx.reply(listing, allowed_mentions=discord.AllowedMentions.none())


@bot.command(name="popular")
async def popular(ctx):
    usage = load_usage()
    top = sorted(usage.items(), key=lambda item: item[1]["count"], reverse=True)[:10]
    if not top:
        await ctx.reply("No snippets have been used yet.")
        return
    lines = [f"{i}. `{name}` – {info['count']} use(s)" for i, (name, info) in enumerate(top, 1)]
    await ctx.reply("\n".join(lines), allowed_mentions=discord.AllowedMentions.none())


@bot.event
async def on_command_error(ctx, error):
    if isinstance(error, (commands.CheckFailure, commands.CommandNotFound)):
        return
    log.error("Command %s failed: %s", ctx.command, error)
    await ctx.reply("Something went wrong running that command.")


if __name__ == "__main__":
    os.makedirs(SNIPPET_ROOT, exist_ok=True)
    bot.run(BOT_TOKEN, log_handler=None)