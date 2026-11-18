import os
import time
import json
import shutil
import logging
from pathlib import Path

from ruamel.yaml import YAML
from watchdog.events import FileSystemEventHandler
from watchdog.observers import Observer

INBOX = Path(os.environ.get("MANIFEST_INBOX", "/srv/shipping/inbox"))
PROCESSED = Path(os.environ.get("MANIFEST_PROCESSED", "/srv/shipping/processed"))
REJECTED = Path(os.environ.get("MANIFEST_REJECTED", "/srv/shipping/rejected"))
LABEL_QUEUE = Path(os.environ.get("LABEL_QUEUE", "/srv/shipping/label-queue"))
SETTLE_SECONDS = 1.5
CARRIERS = {"ups", "fedex", "usps", "dhl"}

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("manifest-watcher")


class ManifestError(Exception):
    pass


def wait_until_stable(path):
    previous = -1
    while True:
        try:
            size = path.stat().st_size
        except FileNotFoundError:
            return False
        if size == previous:
            return True
        previous = size
        time.sleep(SETTLE_SECONDS)


def load_manifest(path):
    yaml = YAML(typ="safe", pure=True)
    with open(path, "r", encoding="utf-8") as handle:
        return yaml.load(handle)


def validate_manifest(manifest):
    if not isinstance(manifest, dict):
        raise ManifestError("manifest must be a mapping")
    carrier = str(manifest.get("carrier", "")).lower()
    if carrier not in CARRIERS:
        raise ManifestError(f"carrier must be one of {', '.join(sorted(CARRIERS))}")
    shipments = manifest.get("shipments")
    if not isinstance(shipments, list) or not shipments:
        raise ManifestError("manifest needs a non-empty shipments list")
    labels = []
    for index, shipment in enumerate(shipments, start=1):
        if not isinstance(shipment, dict):
            raise ManifestError(f"shipment {index} must be a mapping")
        try:
            weight = float(shipment["weight_lb"])
            postal = str(shipment["postal_code"]).strip()
            reference = str(shipment.get("reference", f"#{index}"))[:40]
        except (KeyError, TypeError, ValueError):
            raise ManifestError(f"shipment {index} needs weight_lb and postal_code")
        if not 0 < weight <= 150:
            raise ManifestError(f"shipment {index}: weight must be between 0 and 150 lb")
        labels.append({"carrier": carrier, "reference": reference, "postal_code": postal,
                       "weight_lb": round(weight, 2), "service": str(shipment.get("service", "ground"))})
    return labels


def move(path, folder):
    folder.mkdir(parents=True, exist_ok=True)
    destination = folder / path.name
    if destination.exists():
        destination = folder / f"{path.stem}-{int(time.time())}{path.suffix}"
    shutil.move(str(path), destination)
    return destination


def process(path):
    if not wait_until_stable(path):
        return
    try:
        labels = validate_manifest(load_manifest(path))
    except Exception as exc:
        log.warning("Rejected %s: %s", path.name, exc)
        move(path, REJECTED)
        return
    LABEL_QUEUE.mkdir(parents=True, exist_ok=True)
    queue_file = LABEL_QUEUE / f"{path.stem}.json"
    queue_file.write_text(json.dumps(labels, indent=2), encoding="utf-8")
    move(path, PROCESSED)
    log.info("Queued %d label(s) from %s", len(labels), path.name)


class ManifestHandler(FileSystemEventHandler):
    def on_created(self, event):
        if not event.is_directory and event.src_path.endswith((".yml", ".yaml")):
            process(Path(event.src_path))

    def on_moved(self, event):
        if not event.is_directory and event.dest_path.endswith((".yml", ".yaml")):
            process(Path(event.dest_path))


def main():
    for folder in (INBOX, PROCESSED, REJECTED, LABEL_QUEUE):
        folder.mkdir(parents=True, exist_ok=True)
    for existing in sorted(INBOX.glob("*.y*ml")):
        process(existing)
    observer = Observer()
    observer.schedule(ManifestHandler(), str(INBOX), recursive=False)
    observer.start()
    log.info("Watching %s for shipping manifests", INBOX)
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        observer.stop()
    observer.join()


if __name__ == "__main__":
    main()