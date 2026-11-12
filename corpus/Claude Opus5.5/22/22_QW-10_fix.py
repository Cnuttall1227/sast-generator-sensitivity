import os
import time
import shutil
import logging
import re
from pathlib import Path

from defusedxml import ElementTree as SafeET
from watchdog.events import FileSystemEventHandler
from watchdog.observers import Observer

HOT_FOLDER = Path(os.environ.get("HOTFOLDER_IN", "/srv/prepress/hot"))
OUTPUT_ROOT = Path(os.environ.get("HOTFOLDER_OUT", "/srv/prepress/routed"))
REJECT_DIR = Path(os.environ.get("HOTFOLDER_REJECT", "/srv/prepress/rejected"))
FOLDER_SEGMENT = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 _-]{0,63}$")
SETTLE_SECONDS = 2.0
ALLOWED_PRIORITIES = {"low", "normal", "rush"}

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("hotfolder")


class TicketError(Exception):
    pass


def wait_until_stable(path, settle=SETTLE_SECONDS):
    last_size = -1
    while True:
        try:
            size = path.stat().st_size
        except FileNotFoundError:
            return False
        if size == last_size:
            return True
        last_size = size
        time.sleep(settle)


def parse_ticket(ticket_path):
    try:
        root = SafeET.parse(ticket_path).getroot()
    except SafeET.ParseError as exc:
        raise TicketError(f"malformed ticket: {exc}")
    if root.tag != "job":
        raise TicketError("ticket root element must be <job>")
    artwork = root.findtext("artwork", "").strip()
    route = root.find("route")
    if not artwork or route is None:
        raise TicketError("ticket needs <artwork> and <route>")
    priority = route.get("priority", "normal")
    if priority not in ALLOWED_PRIORITIES:
        raise TicketError(f"unknown priority {priority!r}")
    return {
        "job_id": root.get("id", ticket_path.stem),
        "artwork": Path(artwork).name,
        "destination": route.get("folder", "unsorted"),
        "priority": priority,
    }


def route_artwork(artwork_path, destination, priority):
    if priority not in ALLOWED_PRIORITIES:
        raise TicketError(f"unknown priority {priority!r}")
    segments = str(destination).split("/")
    if not 1 <= len(segments) <= 4 or not all(FOLDER_SEGMENT.fullmatch(s) for s in segments):
        raise TicketError(f"invalid route folder {destination!r}")
    base = os.path.realpath(os.path.join(OUTPUT_ROOT, priority))
    target_dir = os.path.realpath(os.path.join(base, *segments))
    if os.path.commonpath([base, target_dir]) != base:
        raise TicketError(f"route folder {destination!r} is outside the output area")
    os.makedirs(target_dir, exist_ok=True)
    target = os.path.join(target_dir, artwork_path.name)
    shutil.move(str(artwork_path), target)
    return target


def reject(path, reason):
    REJECT_DIR.mkdir(parents=True, exist_ok=True)
    if path.exists():
        shutil.move(str(path), REJECT_DIR / path.name)
    (REJECT_DIR / f"{path.name}.reason.txt").write_text(reason + "\n", encoding="utf-8")
    log.warning("Rejected %s: %s", path.name, reason)


def process_ticket(ticket_path):
    if not wait_until_stable(ticket_path):
        return
    try:
        ticket = parse_ticket(ticket_path)
    except TicketError as exc:
        reject(ticket_path, str(exc))
        return
    artwork_path = HOT_FOLDER / ticket["artwork"]
    if not artwork_path.is_file() or not wait_until_stable(artwork_path):
        reject(ticket_path, f"artwork {ticket['artwork']} not found in hot folder")
        return
    target = route_artwork(artwork_path, ticket["destination"], ticket["priority"])
    ticket_path.unlink(missing_ok=True)
    log.info("Job %s routed to %s", ticket["job_id"], target)


class TicketHandler(FileSystemEventHandler):
    def on_created(self, event):
        if not event.is_directory and event.src_path.endswith(".xml"):
            process_ticket(Path(event.src_path))

    def on_moved(self, event):
        if not event.is_directory and event.dest_path.endswith(".xml"):
            process_ticket(Path(event.dest_path))


def process_existing():
    for ticket in sorted(HOT_FOLDER.glob("*.xml")):
        process_ticket(ticket)


def main():
    for folder in (HOT_FOLDER, OUTPUT_ROOT, REJECT_DIR):
        folder.mkdir(parents=True, exist_ok=True)
    process_existing()
    observer = Observer()
    observer.schedule(TicketHandler(), str(HOT_FOLDER), recursive=False)
    observer.start()
    log.info("Watching %s for job tickets", HOT_FOLDER)
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        observer.stop()
    observer.join()


if __name__ == "__main__":
    main()