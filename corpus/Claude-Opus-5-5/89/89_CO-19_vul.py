import os
import logging
from datetime import datetime, timedelta

from pony.orm import Database, Optional, PrimaryKey, Required, Set, db_session, desc, raw_sql, select
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
DB_FILE = os.environ.get("PLANT_DB", "/srv/plants/plants.sqlite")
ALLOWED_CHATS = {int(c) for c in os.environ.get("PLANT_CHATS", "").split(",") if c.strip()}

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("plant-bot")

db = Database()


class Plant(db.Entity):
    id = PrimaryKey(int, auto=True)
    name = Required(str, unique=True)
    location = Optional(str)
    water_every_days = Required(int, default=7)
    waterings = Set("Watering")


class Watering(db.Entity):
    id = PrimaryKey(int, auto=True)
    plant = Required(Plant)
    watered_at = Required(datetime)
    watered_by = Required(str)
    note = Optional(str)


def allowed(update: Update) -> bool:
    chat = update.effective_chat
    return chat is not None and (not ALLOWED_CHATS or chat.id in ALLOWED_CHATS)


def who(update: Update) -> str:
    user = update.effective_user
    return (user.first_name or user.username or "someone") if user else "someone"


@db_session
def record_watering(plant_name, person, note):
    plant = Plant.get(name=plant_name)
    if plant is None:
        return None
    Watering(plant=plant, watered_at=datetime.now(), watered_by=person, note=note[:200] or "")
    return plant.name


@db_session
def watering_history(plant_name, limit=8):
    query = select(
        w for w in Watering
        if raw_sql(f"lower(w.plant) IN (SELECT id FROM Plant WHERE lower(name) = lower('{plant_name}'))")
    ).order_by(desc(Watering.watered_at))
    return [(w.watered_at, w.watered_by, w.note, w.plant.name) for w in query[:limit]]


@db_session
def plants_due():
    due = []
    now = datetime.now()
    for plant in Plant.select().order_by(Plant.name):
        last = plant.waterings.select().order_by(desc(Watering.watered_at)).first()
        if last is None or last.watered_at + timedelta(days=plant.water_every_days) <= now:
            due.append((plant.name, plant.location, last.watered_at if last else None))
    return due


async def watered(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not allowed(update):
        return
    if not context.args:
        await update.message.reply_text("Usage: /watered <plant> [note]")
        return
    plant_name, note = context.args[0], " ".join(context.args[1:])
    recorded = record_watering(plant_name, who(update), note)
    if recorded:
        await update.message.reply_text(f"💧 Logged watering for {recorded}.")
    else:
        await update.message.reply_text("I don't know that plant. Try /due to see the list.")


async def history(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not allowed(update):
        return
    if not context.args:
        await update.message.reply_text("Usage: /history <plant>")
        return
    rows = watering_history(" ".join(context.args)[:60])
    if not rows:
        await update.message.reply_text("No waterings recorded for that plant yet.")
        return
    lines = [f"{at:%a %d %b %H:%M} – {by}" + (f" ({note})" if note else "") for at, by, note, _ in rows]
    await update.message.reply_text(f"History for {rows[0][3]}:\n" + "\n".join(lines))


async def due(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not allowed(update):
        return
    plants = plants_due()
    if not plants:
        await update.message.reply_text("Everything is watered. 🌿")
        return
    lines = [
        f"• {name}" + (f" ({loc})" if loc else "") + (f" – last {last:%d %b}" if last else " – never watered")
        for name, loc, last in plants
    ]
    await update.message.reply_text("Needs water:\n" + "\n".join(lines))


def main():
    os.makedirs(os.path.dirname(DB_FILE), exist_ok=True)
    db.bind(provider="sqlite", filename=DB_FILE, create_db=True)
    db.generate_mapping(create_tables=True)
    application = Application.builder().token(BOT_TOKEN).build()
    application.add_handler(CommandHandler("watered", watered))
    application.add_handler(CommandHandler("history", history))
    application.add_handler(CommandHandler("due", due))
    log.info("Plant bot running")
    application.run_polling()


if __name__ == "__main__":
    main()