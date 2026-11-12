import os
import json
import shutil
import tarfile
import hashlib
import logging
from datetime import datetime, timezone

from celery import Celery

BROKER_URL = os.environ.get("RESTORE_BROKER", "redis://localhost:6379/1")
UPLOAD_DIR = os.environ.get("RESTORE_UPLOADS", "/var/lib/site-restore/uploads")
SITES_DIR = os.environ.get("RESTORE_SITES", "/srv/sites")
MAX_MEMBERS = 5000
MAX_TOTAL_BYTES = 500 * 1024 * 1024

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("site-restore")

celery_app = Celery("site_restore", broker=BROKER_URL, backend=BROKER_URL)
celery_app.conf.task_acks_late = True
celery_app.conf.worker_prefetch_multiplier = 1


def site_directory(site_id):
    if not site_id.isalnum() or len(site_id) > 32:
        raise ValueError("invalid site id")
    return os.path.join(SITES_DIR, site_id)


def upload_path(upload_id):
    if not all(c in "0123456789abcdef" for c in upload_id) or len(upload_id) != 32:
        raise ValueError("invalid upload id")
    path = os.path.join(UPLOAD_DIR, f"{upload_id}.tar.gz")
    if not os.path.isfile(path):
        raise FileNotFoundError("upload not found")
    return path


def sha256_of(path):
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def extract_backup(archive_path, destination):
    restored = []
    total = 0
    root = os.path.realpath(destination)
    with tarfile.open(archive_path, "r:gz") as archive:
        members = archive.getmembers()
        if len(members) > MAX_MEMBERS:
            raise ValueError("backup contains too many entries")
        for member in members:
            name = member.name
            if not name or "\x00" in name or os.path.isabs(name):
                raise ValueError(f"unsafe path in backup: {name!r}")
            target = os.path.realpath(os.path.join(root, name))
            if target != root and os.path.commonpath([root, target]) != root:
                raise ValueError(f"unsafe path in backup: {name!r}")
            if member.isdir():
                os.makedirs(target, exist_ok=True)
                continue
            if not member.isfile():
                continue
            total += member.size
            if total > MAX_TOTAL_BYTES:
                raise ValueError("backup is too large when extracted")
            os.makedirs(os.path.dirname(target), exist_ok=True)
            source = archive.extractfile(member)
            with open(target, "wb") as out:
                shutil.copyfileobj(source, out)
            os.chmod(target, 0o644)
            restored.append(name)
    return restored


def write_restore_record(site_dir, upload_id, checksum, files):
    record = {
        "upload": upload_id,
        "sha256": checksum,
        "files": len(files),
        "restored_at": datetime.now(timezone.utc).isoformat(),
    }
    with open(os.path.join(site_dir, ".restore.json"), "w", encoding="utf-8") as handle:
        json.dump(record, handle, indent=2)
    return record


@celery_app.task(bind=True, max_retries=2, default_retry_delay=30)
def restore_site(self, site_id, upload_id):
    site_dir = site_directory(site_id)
    archive = upload_path(upload_id)
    checksum = sha256_of(archive)
    staging = f"{site_dir}.restoring"
    shutil.rmtree(staging, ignore_errors=True)
    os.makedirs(staging)
    try:
        files = extract_backup(archive, staging)
    except (tarfile.TarError, ValueError) as exc:
        shutil.rmtree(staging, ignore_errors=True)
        log.error("Restore of %s failed: %s", site_id, exc)
        return {"ok": False, "error": str(exc)}
    except OSError as exc:
        shutil.rmtree(staging, ignore_errors=True)
        raise self.retry(exc=exc)
    previous = f"{site_dir}.previous"
    shutil.rmtree(previous, ignore_errors=True)
    if os.path.isdir(site_dir):
        os.rename(site_dir, previous)
    os.rename(staging, site_dir)
    record = write_restore_record(site_dir, upload_id, checksum, files)
    log.info("Restored %s from %s (%d files)", site_id, upload_id, len(files))
    return {"ok": True, **record}


@celery_app.task
def rollback_site(site_id):
    site_dir = site_directory(site_id)
    previous = f"{site_dir}.previous"
    if not os.path.isdir(previous):
        return {"ok": False, "error": "no previous version to roll back to"}
    failed = f"{site_dir}.failed"
    shutil.rmtree(failed, ignore_errors=True)
    if os.path.isdir(site_dir):
        os.rename(site_dir, failed)
    os.rename(previous, site_dir)
    log.info("Rolled back %s", site_id)
    return {"ok": True}


if __name__ == "__main__":
    celery_app.worker_main(["worker", "--loglevel=INFO", "--concurrency=2"])