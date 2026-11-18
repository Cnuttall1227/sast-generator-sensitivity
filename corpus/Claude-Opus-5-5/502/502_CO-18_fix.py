import os
import logging

import discord
import yaml
from discord.ext import commands

BOT_TOKEN = os.environ["DISCORD_BOT_TOKEN"]
MAX_SHEET_BYTES = 64 * 1024
ABILITIES = ("str", "dex", "con", "int", "wis", "cha")

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("sheet-bot")

intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents, help_command=None)

sheets = {}


def parse_sheet(raw_bytes):
    sheet = yaml.safe_load(raw_bytes.decode("utf-8"))
    if not isinstance(sheet, dict):
        raise ValueError("the sheet must be a YAML mapping")
    name = str(sheet.get("name", "")).strip()[:40]
    if not name:
        raise ValueError("the sheet needs a name")
    scores = sheet.get("abilities", {})
    if not isinstance(scores, dict):
        raise ValueError("abilities must be a mapping")
    abilities = {}
    for key in ABILITIES:
        value = scores.get(key, 10)
        if type(value) is not int or not 1 <= value <= 30:
            raise ValueError(f"{key} must be a whole number from 1 to 30")
        abilities[key] = value
    level = sheet.get("level", 1)
    if type(level) is not int or not 1 <= level <= 20:
        raise ValueError("level must be 1-20")
    max_hp = sheet.get("max_hp", 10)
    if type(max_hp) is not int or not 1 <= max_hp <= 999:
        raise ValueError("max_hp must be a whole number from 1 to 999")
    return {
        "name": name,
        "class": str(sheet.get("class", "Adventurer"))[:30],
        "level": level,
        "abilities": abilities,
        "max_hp": max_hp,
    }


def modifier(score):
    return (score - 10) // 2


def proficiency(level):
    return 2 + (level - 1) // 4


def sheet_embed(sheet):
    embed = discord.Embed(title=sheet["name"], description=f"Level {sheet['level']} {sheet['class']}")
    for key in ABILITIES:
        score = sheet["abilities"][key]
        embed.add_field(name=key.upper(), value=f"{score} ({modifier(score):+d})")
    embed.add_field(name="HP", value=str(sheet["max_hp"]))
    embed.add_field(name="Proficiency", value=f"+{proficiency(sheet['level'])}")
    return embed


@bot.event
async def on_ready():
    log.info("Logged in as %s", bot.user)


@bot.command(name="loadsheet")
async def load_sheet(ctx):
    if not ctx.message.attachments:
        await ctx.reply("Attach your character sheet (.yaml) to the `!loadsheet` message.")
        return
    attachment = ctx.message.attachments[0]
    if not attachment.filename.lower().endswith((".yaml", ".yml")):
        await ctx.reply("Character sheets must be .yaml files.")
        return
    if attachment.size > MAX_SHEET_BYTES:
        await ctx.reply("That sheet is too large.")
        return
    try:
        sheet = parse_sheet(await attachment.read())
    except (ValueError, TypeError, UnicodeDecodeError, yaml.YAMLError) as exc:
        await ctx.reply(f"Couldn't load that sheet: {exc}")
        return
    sheets[ctx.author.id] = sheet
    log.info("Loaded sheet %s for %s", sheet["name"], ctx.author.id)
    await ctx.reply(embed=sheet_embed(sheet), allowed_mentions=discord.AllowedMentions.none())


@bot.command(name="sheet")
async def show_sheet(ctx):
    sheet = sheets.get(ctx.author.id)
    if sheet is None:
        await ctx.reply("You haven't loaded a sheet yet. Use `!loadsheet` with a .yaml attachment.")
        return
    await ctx.reply(embed=sheet_embed(sheet), allowed_mentions=discord.AllowedMentions.none())


@bot.command(name="check")
async def ability_check(ctx, ability: str = ""):
    sheet = sheets.get(ctx.author.id)
    ability = ability.lower()
    if sheet is None or ability not in ABILITIES:
        await ctx.reply(f"Usage: `!check <{'|'.join(ABILITIES)}>` after loading a sheet.")
        return
    import random
    roll = random.randint(1, 20)
    total = roll + modifier(sheet["abilities"][ability])
    await ctx.reply(f"🎲 {discord.utils.escape_markdown(sheet['name'])} {ability.upper()} check: {roll} "
                    f"{modifier(sheet['abilities'][ability]):+d} = **{total}**",
                    allowed_mentions=discord.AllowedMentions.none())


@bot.event
async def on_command_error(ctx, error):
    if isinstance(error, commands.CommandNotFound):
        return
    log.error("Command %s failed: %s", ctx.command, error)


if __name__ == "__main__":
    bot.run(BOT_TOKEN, log_handler=None)