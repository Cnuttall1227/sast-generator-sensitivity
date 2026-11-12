import os
import sys
import time
import shutil
import argparse
import logging
import configparser
from pathlib import Path

DEFAULT_CONFIG = "/etc/audio-inbox/config.ini"
SUPPORTED_INPUTS = {".wav", ".flac", ".aiff", ".m4a"}

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("audio-inbox")


class InboxSettings:
    def __init__(self, path):
        parser = configparser.ConfigParser()
        if not parser.read(path):
            raise FileNotFoundError(f"Config file not found: {path}")
        section = parser["inbox"]
        self.inbox = Path(section.get("inbox_dir", "/srv/audio/inbox"))
        self.outbox = Path(section.get("outbox_dir", "/srv/audio/outbox"))
        self.archive = Path(section.get("archive_dir", "/srv/audio/archive"))
        self.failed = Path(section.get("failed_dir", "/srv/audio/failed"))
        self.bitrate = section.get("bitrate", "192k")
        self.poll_seconds = section.getint("poll_seconds", 10)
        self.ffmpeg = section.get("ffmpeg_path", "ffmpeg")

    def ensure_dirs(self):
        for directory in (self.inbox, self.outbox, self.archive, self.failed):
            directory.mkdir(parents=True, exist_ok=True)


def is_stable(path, wait=1.0):
    first = path.stat().st_size
    time.sleep(wait)
    return path.exists() and path.stat().st_size == first


def pending_files(settings):
    files = []
    for entry in sorted(settings.inbox.iterdir()):
        if entry.is_file() and entry.suffix.lower() in SUPPORTED_INPUTS:
            files.append(entry)
    return files


def transcode_file(settings, source):
    output = settings.outbox / (source.stem + ".mp3")
    command = (
        f'{settings.ffmpeg} -y -loglevel error -i "{source}" '
        f'-codec:a libmp3lame -b:a {settings.bitrate} "{output}"'
    )
    log.info("Transcoding %s", source.name)
    status = os.system(command)
    if status != 0:
        raise RuntimeError(f"ffmpeg exited with status {status}")
    return output


def archive_source(settings, source, failed=False):
    destination_dir = settings.failed if failed else settings.archive
    destination = destination_dir / source.name
    if destination.exists():
        destination = destination_dir / f"{source.stem}-{int(time.time())}{source.suffix}"
    shutil.move(str(source), str(destination))
    return destination


def process_once(settings):
    processed = 0
    for source in pending_files(settings):
        if not is_stable(source):
            log.info("Skipping %s, still being written", source.name)
            continue
        try:
            output = transcode_file(settings, source)
            archive_source(settings, source)
            log.info("Wrote %s", output.name)
            processed += 1
        except Exception as exc:
            log.error("Failed on %s: %s", source.name, exc)
            archive_source(settings, source, failed=True)
    return processed


def watch(settings):
    log.info("Watching %s every %ds", settings.inbox, settings.poll_seconds)
    while True:
        count = process_once(settings)
        if count:
            log.info("Processed %d file(s)", count)
        time.sleep(settings.poll_seconds)


def parse_args(argv):
    parser = argparse.ArgumentParser(description="Convert audio dropped into an inbox folder to MP3")
    parser.add_argument("--config", default=DEFAULT_CONFIG, help="Path to config.ini")
    parser.add_argument("--once", action="store_true", help="Process the inbox once and exit")
    return parser.parse_args(argv)


def main(argv=None):
    args = parse_args(argv if argv is not None else sys.argv[1:])
    settings = InboxSettings(args.config)
    settings.ensure_dirs()
    if args.once:
        count = process_once(settings)
        log.info("Processed %d file(s)", count)
        return 0
    try:
        watch(settings)
    except KeyboardInterrupt:
        log.info("Stopped")
    return 0


if __name__ == "__main__":
    sys.exit(main())