import os
import re
import logging
import ast
import operator

from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
MAX_EXPRESSION_LENGTH = 60

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("unit-bot")

TO_BASE = {
    "mm": ("length", 0.001), "cm": ("length", 0.01), "m": ("length", 1.0), "km": ("length", 1000.0),
    "in": ("length", 0.0254), "inch": ("length", 0.0254), "ft": ("length", 0.3048),
    "yd": ("length", 0.9144), "mi": ("length", 1609.344),
    "g": ("mass", 0.001), "kg": ("mass", 1.0), "oz": ("mass", 0.028349523125), "lb": ("mass", 0.45359237),
    "ml": ("volume", 0.001), "l": ("volume", 1.0), "cup": ("volume", 0.2365882365),
    "tbsp": ("volume", 0.01478676478125), "tsp": ("volume", 0.00492892159375), "gal": ("volume", 3.785411784),
}
TEMPERATURES = {"c", "f", "k"}
REQUEST_PATTERN = re.compile(r"^(?P<amount>.+?)\s*(?P<src>[a-z]+)\s+(?:to|in)\s+(?P<dst>[a-z]+)$", re.IGNORECASE)

HELP = (
    "Convert units, e.g.\n"
    "/convert 12 in to cm\n"
    "/convert 3*250 g to lb\n"
    "/convert 350 f to c\n"
    "Supported: " + ", ".join(sorted(TO_BASE)) + ", c, f, k"
)

AMOUNT_OPERATORS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
}


def evaluate_amount(expression):
    if len(expression) > MAX_EXPRESSION_LENGTH:
        raise ValueError("that amount is too long")
    tree = ast.parse(expression, mode="eval")

    def ev(node):
        if isinstance(node, ast.Expression):
            return ev(node.body)
        if isinstance(node, ast.Constant) and type(node.value) in (int, float):
            return node.value
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)):
            value = ev(node.operand)
            return -value if isinstance(node.op, ast.USub) else value
        if isinstance(node, ast.BinOp) and type(node.op) in AMOUNT_OPERATORS:
            return AMOUNT_OPERATORS[type(node.op)](ev(node.left), ev(node.right))
        raise ValueError("amounts can only use numbers, + - * / and brackets")

    value = float(ev(tree))
    if value != value or value in (float("inf"), float("-inf")):
        raise ValueError("that amount isn't a finite number")
    return value


def convert_temperature(value, src, dst):
    celsius = {"c": value, "f": (value - 32) * 5 / 9, "k": value - 273.15}[src]
    return {"c": celsius, "f": celsius * 9 / 5 + 32, "k": celsius + 273.15}[dst]


def convert(value, src, dst):
    if src in TEMPERATURES and dst in TEMPERATURES:
        return convert_temperature(value, src, dst)
    if src not in TO_BASE or dst not in TO_BASE:
        raise ValueError("I don't know one of those units")
    src_kind, src_factor = TO_BASE[src]
    dst_kind, dst_factor = TO_BASE[dst]
    if src_kind != dst_kind:
        raise ValueError(f"can't convert {src_kind} to {dst_kind}")
    return value * src_factor / dst_factor


def format_number(value):
    if value == 0:
        return "0"
    if abs(value) >= 1000 or abs(value) < 0.01:
        return f"{value:.4g}"
    return f"{value:.3f}".rstrip("0").rstrip(".")


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(HELP)


async def convert_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = " ".join(context.args).strip()
    match = REQUEST_PATTERN.match(text)
    if not match:
        await update.message.reply_text(HELP)
        return
    src, dst = match["src"].lower(), match["dst"].lower()
    try:
        amount = evaluate_amount(match["amount"].strip())
        result = convert(amount, src, dst)
    except ZeroDivisionError:
        await update.message.reply_text("That amount divides by zero.")
        return
    except (ValueError, TypeError, SyntaxError, NameError) as exc:
        await update.message.reply_text(f"Sorry, {exc}." if isinstance(exc, ValueError) else "I couldn't read that amount.")
        return
    log.info("Converted %s %s to %s", format_number(amount), src, dst)
    await update.message.reply_text(f"{format_number(amount)} {src} = {format_number(result)} {dst}")


def main():
    application = Application.builder().token(BOT_TOKEN).build()
    application.add_handler(CommandHandler(["start", "help"], start))
    application.add_handler(CommandHandler("convert", convert_command))
    log.info("Unit converter bot running")
    application.run_polling()


if __name__ == "__main__":
    main()