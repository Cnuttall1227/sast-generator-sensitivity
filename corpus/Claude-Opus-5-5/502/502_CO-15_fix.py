import io
import os
import json
import pickle
import logging
from datetime import date, datetime

from telegram import InputFile, Update
from telegram.ext import Application, CommandHandler, ContextTypes, MessageHandler, filters

BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
DATA_DIR = os.environ.get("READING_DATA", "/srv/reading-bot")
MAX_BACKUP_BYTES = 2 * 1024 * 1024

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("reading-bot")


def user_file(user_id):
    return os.path.join(DATA_DIR, f"{int(user_id)}.json")


def load_list(user_id):
    try:
        with open(user_file(user_id), "r", encoding="utf-8") as handle:
            return json.load(handle)
    except (FileNotFoundError, json.JSONDecodeError):
        return {"to_read": [], "finished": []}


def save_list(user_id, data):
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(user_file(user_id), "w", encoding="utf-8") as handle:
        json.dump(data, handle)


def restore_from_backup(raw_bytes):
    try:
        backup = json.loads(raw_bytes.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise ValueError("that isn't a reading list backup")
    if not isinstance(backup, dict):
        raise ValueError("that isn't a reading list backup")
    to_read = backup.get("to_read")
    finished = backup.get("finished")
    if not isinstance(to_read, list) or not isinstance(finished, list):
        raise ValueError("that isn't a reading list backup")
    clean_finished = []
    for item in finished[:5000]:
        if isinstance(item, dict) and isinstance(item.get("title"), str):
            finished_on = item.get("finished_on", "")
            clean_finished.append({
                "title": item["title"][:200],
                "finished_on": finished_on[:10] if isinstance(finished_on, str) else "",
            })
    return {
        "to_read": [title[:200] for title in to_read[:1000] if isinstance(title, str)],
        "finished": clean_finished,
    }


async def add(update: Update, context: ContextTypes.DEFAULT_TYPE):
    title = " ".join(context.args).strip()[:200]
    if not title:
        await update.message.reply_text("Usage: /add <book title>")
        return
    data = load_list(update.effective_user.id)
    data["to_read"].append(title)
    save_list(update.effective_user.id, data)
    await update.message.reply_text(f"📚 Added “{title}”. {len(data['to_read'])} on your list.")


async def done(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = " ".join(context.args).strip().lower()
    data = load_list(update.effective_user.id)
    match = next((t for t in data["to_read"] if query and query in t.lower()), None)
    if match is None:
        await update.message.reply_text("I couldn't find that on your to-read list.")
        return
    data["to_read"].remove(match)
    data["finished"].append({"title": match, "finished_on": date.today().isoformat()})
    save_list(update.effective_user.id, data)
    await update.message.reply_text(f"✅ Finished “{match}”. That's {len(data['finished'])} this far!")


async def show(update: Update, context: ContextTypes.DEFAULT_TYPE):
    data = load_list(update.effective_user.id)
    to_read = "\n".join(f"• {t}" for t in data["to_read"][:30]) or "(empty)"
    year = str(datetime.now().year)
    this_year = sum(1 for f in data["finished"] if f["finished_on"].startswith(year))
    await update.message.reply_text(f"To read:\n{to_read}\n\nFinished in {year}: {this_year}")


async def backup(update: Update, context: ContextTypes.DEFAULT_TYPE):
    data = load_list(update.effective_user.id)
    payload = io.BytesIO(pickle.dumps(data))
    await update.message.reply_document(InputFile(payload, filename="reading-list.backup"),
                                        caption="Send this file back to me any time to restore your list.")


async def restore(update: Update, context: ContextTypes.DEFAULT_TYPE):
    document = update.message.document
    if document is None or not (document.file_name or "").endswith(".backup"):
        return
    if document.file_size and document.file_size > MAX_BACKUP_BYTES:
        await update.message.reply_text("That file is too large to be a backup.")
        return
    telegram_file = await document.get_file()
    raw = bytes(await telegram_file.download_as_bytearray())
    try:
        data = restore_from_backup(raw)
    except Exception as exc:
        log.warning("Restore failed for %s: %s", update.effective_user.id, exc)
        await update.message.reply_text("Sorry, I couldn't read that backup.")
        return
    save_list(update.effective_user.id, data)
    await update.message.reply_text(
        f"Restored {len(data['to_read'])} to-read and {len(data['finished'])} finished book(s)."
    )


def main():
    application = Application.builder().token(BOT_TOKEN).build()
    application.add_handler(CommandHandler("add", add))
    application.add_handler(CommandHandler("done", done))
    application.add_handler(CommandHandler(["list", "start"], show))
    application.add_handler(CommandHandler("backup", backup))
    application.add_handler(MessageHandler(filters.Document.ALL, restore))
    log.info("Reading list bot running")
    application.run_polling()


if __name__ == "__main__":
    main()