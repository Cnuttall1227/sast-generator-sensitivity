import os
import re
import logging
from datetime import datetime, timezone
from pathlib import Path

from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes, MessageHandler, filters

BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
ARCHIVE_ROOT = os.environ.get("RECEIPT_ARCHIVE", "/srv/receipts")
ALLOWED_USERS = {int(u) for u in os.environ.get("RECEIPT_USERS", "").split(",") if u.strip()}
MAX_FILE_BYTES = 20 * 1024 * 1024
ALLOWED_EXTENSIONS = {".pdf", ".jpg", ".jpeg", ".png", ".heic"}
DEFAULT_FOLDER = "inbox"

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("receipt-bot")

HELP_TEXT = (
    "Send a receipt photo or PDF. Add a caption like `taxes/2026` to file it in that folder, "
    "otherwise it goes to `inbox`.\n"
    "/folders – list folders\n"
    "/recent – show the last 10 receipts"
)


def allowed(update: Update) -> bool:
    user = update.effective_user
    return user is not None and (not ALLOWED_USERS or user.id in ALLOWED_USERS)


def archive_target(caption, original_name):
    folder = (caption or DEFAULT_FOLDER).strip() or DEFAULT_FOLDER
    extension = Path(original_name).suffix.lower()
    if extension not in ALLOWED_EXTENSIONS:
        raise ValueError(f"{extension or 'that file type'} is not accepted")
    target_dir = os.path.join(ARCHIVE_ROOT, folder)
    os.makedirs(target_dir, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    safe_stem = re.sub(r"[^A-Za-z0-9_-]+", "_", Path(original_name).stem)[:40] or "receipt"
    return os.path.join(target_dir, f"{stamp}-{safe_stem}{extension}"), folder


def list_folders():
    folders = []
    for current, dirs, _ in os.walk(ARCHIVE_ROOT):
        dirs[:] = [d for d in dirs if not d.startswith(".")]
        for name in dirs:
            folders.append(os.path.relpath(os.path.join(current, name), ARCHIVE_ROOT))
    return sorted(folders)


def recent_receipts(limit=10):
    files = []
    for current, _, names in os.walk(ARCHIVE_ROOT):
        for name in names:
            full = os.path.join(current, name)
            files.append((os.path.getmtime(full), os.path.relpath(full, ARCHIVE_ROOT)))
    return [path for _, path in sorted(files, reverse=True)[:limit]]


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if allowed(update):
        await update.message.reply_text(HELP_TEXT, parse_mode="Markdown")


async def folders(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not allowed(update):
        return
    names = list_folders()
    await update.message.reply_text("\n".join(names) if names else "No folders yet.")


async def recent(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not allowed(update):
        return
    items = recent_receipts()
    await update.message.reply_text("\n".join(items) if items else "Nothing archived yet.")


async def receive_file(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not allowed(update):
        return
    message = update.message
    if message.document:
        telegram_file, original = message.document, message.document.file_name or "receipt.pdf"
    elif message.photo:
        telegram_file, original = message.photo[-1], "photo.jpg"
    else:
        return
    if telegram_file.file_size and telegram_file.file_size > MAX_FILE_BYTES:
        await message.reply_text("That file is too large.")
        return
    try:
        target, folder = archive_target(message.caption, original)
    except ValueError as exc:
        await message.reply_text(str(exc))
        return
    downloaded = await telegram_file.get_file()
    await downloaded.download_to_drive(custom_path=target)
    log.info("User %s archived %s", update.effective_user.id, target)
    await message.reply_text(f"Saved to {folder}/{os.path.basename(target)}")


def main():
    os.makedirs(ARCHIVE_ROOT, exist_ok=True)
    application = Application.builder().token(BOT_TOKEN).build()
    application.add_handler(CommandHandler(["start", "help"], start))
    application.add_handler(CommandHandler("folders", folders))
    application.add_handler(CommandHandler("recent", recent))
    application.add_handler(MessageHandler(filters.Document.ALL | filters.PHOTO, receive_file))
    log.info("Receipt bot running")
    application.run_polling()


if __name__ == "__main__":
    main()