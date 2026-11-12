import os
import re
import json
import hashlib
import logging
import subprocess
from pathlib import Path
from urllib.parse import urljoin, urlparse

import scrapy
from scrapy.crawler import CrawlerProcess

START_URL = os.environ.get("FIRMWARE_PAGE", "https://vendor.example.com/support/firmware")
ALLOWED_HOST = urlparse(START_URL).hostname
MIRROR_DIR = Path(os.environ.get("FIRMWARE_MIRROR", "/srv/firmware-mirror"))
MANIFEST = MIRROR_DIR / "manifest.json"
FIRMWARE_EXTENSIONS = (".bin", ".img", ".zip", ".fw")
DOWNLOAD_TIMEOUT = 600
SAFE_FILENAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("firmware-mirror")


class FirmwareItem(scrapy.Item):
    model = scrapy.Field()
    version = scrapy.Field()
    filename = scrapy.Field()
    url = scrapy.Field()
    sha256 = scrapy.Field()


class FirmwareSpider(scrapy.Spider):
    name = "firmware"
    allowed_domains = [ALLOWED_HOST]
    start_urls = [START_URL]
    custom_settings = {
        "ROBOTSTXT_OBEY": True,
        "DOWNLOAD_DELAY": 1.0,
        "ITEM_PIPELINES": {"__main__.MirrorPipeline": 300},
        "LOG_LEVEL": "INFO",
    }

    def parse(self, response):
        for row in response.css("table.firmware tr"):
            link = row.css("a.download")
            href = link.attrib.get("href")
            if not href:
                continue
            url = urljoin(response.url, href)
            if urlparse(url).hostname != ALLOWED_HOST:
                continue
            filename = (link.attrib.get("download") or link.css("::text").get() or "").strip()
            if not filename.lower().endswith(FIRMWARE_EXTENSIONS):
                continue
            yield FirmwareItem(
                model=(row.css("td.model::text").get() or "").strip(),
                version=(row.css("td.version::text").get() or "").strip(),
                filename=filename,
                url=url,
                sha256=(row.css("td.sha256::text").get() or "").strip().lower(),
            )
        next_page = response.css("a.next::attr(href)").get()
        if next_page:
            yield response.follow(next_page, callback=self.parse)


def file_digest(path):
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def download_firmware(url, filename):
    name = Path(filename).name
    if not SAFE_FILENAME.fullmatch(name) or not name.lower().endswith(FIRMWARE_EXTENSIONS):
        raise ValueError(f"unsafe firmware filename {filename!r}")
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https") or parsed.hostname != ALLOWED_HOST:
        raise ValueError(f"unexpected download URL {url!r}")
    MIRROR_DIR.mkdir(parents=True, exist_ok=True)
    target = (MIRROR_DIR / name).resolve()
    if target.parent != MIRROR_DIR.resolve():
        raise ValueError("download path escapes mirror folder")
    command = [
        "curl", "--fail", "--silent", "--show-error", "--location",
        "--proto", "=http,https",
        "--max-time", str(DOWNLOAD_TIMEOUT),
        "--output", str(target),
        "--url", url,
    ]
    subprocess.run(command, check=True)
    return target

class MirrorPipeline:
    def open_spider(self, spider):
        self.manifest = json.loads(MANIFEST.read_text()) if MANIFEST.exists() else {}
        self.new_files = 0

    def close_spider(self, spider):
        MIRROR_DIR.mkdir(parents=True, exist_ok=True)
        MANIFEST.write_text(json.dumps(self.manifest, indent=2))
        log.info("Mirror run finished, %d new file(s)", self.new_files)

    def process_item(self, item, spider):
        key = item["url"]
        if key in self.manifest and self.manifest[key].get("sha256") == item["sha256"]:
            return item
        try:
            path = download_firmware(item["url"], item["filename"])
        except subprocess.CalledProcessError as exc:
            log.error("Download failed for %s: exit %s", item["url"], exc.returncode)
            return item
        actual = file_digest(path)
        if item["sha256"] and not re.fullmatch(item["sha256"], actual):
            log.error("Checksum mismatch for %s", item["filename"])
            path.unlink(missing_ok=True)
            return item
        self.manifest[key] = {
            "model": item["model"],
            "version": item["version"],
            "file": path.name,
            "sha256": actual,
        }
        self.new_files += 1
        log.info("Mirrored %s %s", item["model"], item["version"])
        return item


if __name__ == "__main__":
    process = CrawlerProcess()
    process.crawl(FirmwareSpider)
    process.start()