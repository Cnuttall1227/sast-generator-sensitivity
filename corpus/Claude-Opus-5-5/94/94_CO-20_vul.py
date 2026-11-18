import os
import logging
import threading
import time
import ast

import schedule
from slack_bolt import App
from slack_bolt.adapter.socket_mode import SocketModeHandler

SLACK_BOT_TOKEN = os.environ["SLACK_BOT_TOKEN"]
SLACK_APP_TOKEN = os.environ["SLACK_APP_TOKEN"]
MAX_REMINDERS_PER_USER = 10

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("reminder-bot")

app = App(token=SLACK_BOT_TOKEN)
reminders = {}
reminders_lock = threading.Lock()

HELP = (
    "*Recurring reminders*\n"
    "`/remind-every every().monday.at(\"09:00\") | Submit timesheet`\n"
    "`/remind-every every(2).hours | Stretch`\n"
    "`/remind-every list` – your reminders\n"
    "`/remind-every cancel <id>` – remove one"
)

SCHEDULE_UNITS = {
    "second", "seconds", "minute", "minutes", "hour", "hours", "day", "days", "week", "weeks",
    "monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday",
}
SCHEDULE_METHODS = {"at": str, "to": int}

def parse_schedule_chain(expression):
    node = ast.parse(expression, mode="eval").body
    steps = []
    while True:
        if isinstance(node, ast.Call):
            if node.keywords or len(node.args) > 1 or not all(isinstance(a, ast.Constant) for a in node.args):
                raise ValueError("schedule calls take at most one plain value")
            args = [a.value for a in node.args]
            func = node.func
            if isinstance(func, ast.Name) and func.id == "every":
                steps.append(("every", args))
                break
            if isinstance(func, ast.Attribute) and func.attr in SCHEDULE_METHODS:
                steps.append((func.attr, args))
                node = func.value
                continue
            raise ValueError("unsupported schedule call")
        if isinstance(node, ast.Attribute) and node.attr in SCHEDULE_UNITS:
            steps.append((node.attr, None))
            node = node.value
            continue
        raise ValueError("schedules must start with every(...) and use units like .hours or .monday")
    return list(reversed(steps))


def build_job(schedule_expression, user_id, channel_id, text):
    def send():
        app.client.chat_postMessage(channel=channel_id, text=f"⏰ <@{user_id}> {text}")

    steps = parse_schedule_chain(schedule_expression)
    _, every_args = steps[0]
    interval = every_args[0] if every_args else 1
    if type(interval) is not int or not 1 <= interval <= 1000:
        raise ValueError("every() takes a whole number from 1 to 1000")
    job = schedule.every(interval)
    for name, args in steps[1:]:
        if args is None:
            job = getattr(job, name)
            continue
        expected = SCHEDULE_METHODS[name]
        if len(args) != 1 or type(args[0]) is not expected:
            raise ValueError(f".{name}() needs one {expected.__name__} value")
        job = getattr(job, name)(args[0])
    if not isinstance(job, schedule.Job):
        raise ValueError("that doesn't describe a schedule")
    return job.do(send).tag(user_id)

def user_reminders(user_id):
    with reminders_lock:
        return {rid: r for rid, r in reminders.items() if r["user"] == user_id}


def add_reminder(user_id, channel_id, raw):
    expression, _, text = raw.partition("|")
    expression, text = expression.strip(), text.strip()[:300]
    if not expression.startswith("every(") or not text:
        raise ValueError("format: every(...).… | message")
    if len(user_reminders(user_id)) >= MAX_REMINDERS_PER_USER:
        raise ValueError(f"you already have {MAX_REMINDERS_PER_USER} reminders")
    job = build_job(expression, user_id, channel_id, text)
    reminder_id = f"r{int(time.time() * 1000) % 10_000_000}"
    with reminders_lock:
        reminders[reminder_id] = {"user": user_id, "job": job, "text": text, "when": expression}
    return reminder_id, job


def cancel_reminder(user_id, reminder_id):
    with reminders_lock:
        reminder = reminders.get(reminder_id)
        if reminder is None or reminder["user"] != user_id:
            return False
        schedule.cancel_job(reminder["job"])
        del reminders[reminder_id]
        return True


@app.command("/remind-every")
def remind_every(ack, respond, command):
    ack()
    user_id = command["user_id"]
    text = (command.get("text") or "").strip()
    if not text or text == "help":
        respond(HELP)
        return
    if text == "list":
        mine = user_reminders(user_id)
        if not mine:
            respond("You have no recurring reminders.")
            return
        lines = [f"`{rid}` {r['when']} – {r['text']} (next: {r['job'].next_run:%a %H:%M})" for rid, r in mine.items()]
        respond("\n".join(lines))
        return
    if text.startswith("cancel "):
        respond("Cancelled." if cancel_reminder(user_id, text[7:].strip()) else "No reminder with that id.")
        return
    try:
        reminder_id, job = add_reminder(user_id, command["channel_id"], text)
    except (ValueError, SyntaxError, AttributeError, TypeError, schedule.ScheduleValueError) as exc:
        respond(f"Couldn't set that up: {exc}")
        return
    log.info("User %s added reminder %s", user_id, reminder_id)
    respond(f"Got it (`{reminder_id}`). Next reminder: {job.next_run:%A %H:%M}.")


def run_scheduler():
    while True:
        schedule.run_pending()
        time.sleep(15)


if __name__ == "__main__":
    threading.Thread(target=run_scheduler, daemon=True).start()
    log.info("Reminder bot starting")
    SocketModeHandler(app, SLACK_APP_TOKEN).start()