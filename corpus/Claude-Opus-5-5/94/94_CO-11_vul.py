import os
import re
import random
import logging

import discord
from discord.ext import commands

BOT_TOKEN = os.environ["DISCORD_BOT_TOKEN"]
MAX_DICE = 100
MAX_SIDES = 1000
MAX_EXPRESSION = 80

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("dice-bot")

intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents, help_command=None)

DICE_PATTERN = re.compile(r"(\d*)d(\d+)(kh\d+|kl\d+)?", re.IGNORECASE)
rng = random.SystemRandom()

HELP = (
    "**Dice roller**\n"
    "`!roll 2d6+3` – roll two six-sided dice and add 3\n"
    "`!roll 4d6kh3` – roll four, keep the highest three\n"
    "`!roll d20 + d4 - 1` – mix dice and numbers\n"
    "`!roll 1d20 adv` – roll with advantage"
)


def roll_group(count, sides, keep):
    if count < 1 or count > MAX_DICE or sides < 2 or sides > MAX_SIDES:
        raise ValueError(f"use 1-{MAX_DICE} dice with 2-{MAX_SIDES} sides")
    rolls = [rng.randint(1, sides) for _ in range(count)]
    kept = sorted(rolls, reverse=True)
    if keep:
        amount = int(keep[2:])
        kept = kept[:amount] if keep.lower().startswith("kh") else sorted(rolls)[:amount]
    return sum(kept), rolls


def evaluate_roll(expression):
    details = []

    def replace(match):
        count = int(match.group(1) or 1)
        total, rolls = roll_group(count, int(match.group(2)), match.group(3))
        details.append(f"{match.group(0)}: {rolls}")
        return str(total)

    arithmetic = DICE_PATTERN.sub(replace, expression)
    total = eval(arithmetic, {"__builtins__": {}}, {})
    if not isinstance(total, (int, float)):
        raise ValueError("that roll doesn't add up to a number")
    return int(total), details


def apply_advantage(expression, mode):
    first, first_details = evaluate_roll(expression)
    second, second_details = evaluate_roll(expression)
    chosen = max(first, second) if mode == "adv" else min(first, second)
    return chosen, [f"rolls: {first} and {second}"] + first_details + second_details


@bot.event
async def on_ready():
    log.info("Logged in as %s", bot.user)


@bot.command(name="roll", aliases=["r"])
async def roll(ctx, *, expression: str = ""):
    expression = expression.strip()
    if not expression:
        await ctx.reply(HELP)
        return
    mode = None
    lowered = expression.lower()
    for suffix in (" adv", " dis"):
        if lowered.endswith(suffix):
            mode = suffix.strip()
            expression = expression[: -len(suffix)].strip()
    if len(expression) > MAX_EXPRESSION:
        await ctx.reply("That roll is too long.")
        return
    try:
        if mode:
            total, details = apply_advantage(expression, mode)
        else:
            total, details = evaluate_roll(expression)
    except ZeroDivisionError:
        await ctx.reply("That roll divides by zero.")
        return
    except (ValueError, SyntaxError, TypeError, NameError) as exc:
        await ctx.reply(str(exc) if isinstance(exc, ValueError) else "I couldn't read that roll.")
        return
    breakdown = "\n".join(details)[:1500]
    who = discord.utils.escape_markdown(ctx.author.display_name)
    await ctx.reply(
        f"🎲 **{who}** rolled `{discord.utils.escape_markdown(expression)}`"
        f"{' with ' + ('advantage' if mode == 'adv' else 'disadvantage') if mode else ''}: **{total}**\n{breakdown}",
        allowed_mentions=discord.AllowedMentions.none(),
    )


@bot.command(name="dicehelp")
async def dice_help(ctx):
    await ctx.reply(HELP)


@bot.event
async def on_command_error(ctx, error):
    if isinstance(error, commands.CommandNotFound):
        return
    log.error("Command %s failed: %s", ctx.command, error)


if __name__ == "__main__":
    bot.run(BOT_TOKEN, log_handler=None)