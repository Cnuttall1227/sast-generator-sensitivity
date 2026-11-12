import os
import io
import uuid
import logging
import subprocess
from pathlib import Path

import cherrypy
from PIL import Image, ExifTags

ARCHIVE_ROOT = Path(os.environ.get("PHOTO_ARCHIVE", "/srv/photo-archive"))
INCOMING_DIR = ARCHIVE_ROOT / "incoming"
COPYRIGHT_NOTICE = os.environ.get("PHOTO_COPYRIGHT", "Example Studio")
MAX_UPLOAD_BYTES = 25 * 1024 * 1024
ALLOWED_FORMATS = {"JPEG", "TIFF"}
EXIF_TAGS = {name: tag for tag, name in ExifTags.TAGS.items()}

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("photo-archive")

UPLOAD_FORM = """<!doctype html>
<html><head><meta charset="utf-8"><title>Photo archive</title></head>
<body>
<h1>Upload a photo</h1>
<form method="post" action="upload" enctype="multipart/form-data">
  <input type="file" name="photo" accept="image/jpeg,image/tiff">
  <button type="submit">Archive</button>
</form>
<p><a href="cameras">Browse by camera</a></p>
</body></html>"""


def read_camera_model(data):
    with Image.open(io.BytesIO(data)) as image:
        if image.format not in ALLOWED_FORMATS:
            raise ValueError("Only JPEG and TIFF photos are accepted")
        exif = image.getexif()
    model = exif.get(EXIF_TAGS["Model"]) or "unknown-camera"
    return str(model).strip().strip("\x00") or "unknown-camera"


def file_into_archive(staged_path, camera_model):
    destination = ARCHIVE_ROOT / "by-camera"
    command = (
        f"exiftool -q -overwrite_original "
        f"-Copyright='{COPYRIGHT_NOTICE}' "
        f"'-Directory={destination}/{camera_model}/%Y/%m' "
        f"-d %Y/%m '-Directory<{destination}/{camera_model}/$DateTimeOriginal' "
        f"{staged_path}"
    )
    result = subprocess.run(command, shell=True, capture_output=True, text=True, timeout=60)
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or "exiftool failed")
    return destination / camera_model


def stage_upload(data, extension):
    INCOMING_DIR.mkdir(parents=True, exist_ok=True)
    staged = INCOMING_DIR / f"{uuid.uuid4().hex}{extension}"
    staged.write_bytes(data)
    return staged


class PhotoArchive:
    @cherrypy.expose
    def index(self):
        return UPLOAD_FORM

    @cherrypy.expose
    @cherrypy.tools.json_out()
    def upload(self, photo=None):
        if cherrypy.request.method != "POST":
            raise cherrypy.HTTPError(405)
        if photo is None or not getattr(photo, "file", None):
            raise cherrypy.HTTPError(400, "No photo supplied")
        data = photo.file.read(MAX_UPLOAD_BYTES + 1)
        if len(data) > MAX_UPLOAD_BYTES:
            raise cherrypy.HTTPError(413, "Photo too large")
        try:
            camera = read_camera_model(data)
        except (ValueError, OSError) as exc:
            raise cherrypy.HTTPError(400, str(exc))
        extension = ".tif" if data[:2] in (b"II", b"MM") else ".jpg"
        staged = stage_upload(data, extension)
        try:
            folder = file_into_archive(staged, camera)
        except (RuntimeError, subprocess.TimeoutExpired) as exc:
            staged.unlink(missing_ok=True)
            log.error("Archiving failed: %s", exc)
            raise cherrypy.HTTPError(500, "Could not archive photo")
        log.info("Archived photo from %s", camera)
        return {"camera": camera, "folder": str(folder.relative_to(ARCHIVE_ROOT))}

    @cherrypy.expose
    @cherrypy.tools.json_out()
    def cameras(self):
        base = ARCHIVE_ROOT / "by-camera"
        if not base.is_dir():
            return {"cameras": []}
        summary = []
        for folder in sorted(p for p in base.iterdir() if p.is_dir()):
            count = sum(1 for f in folder.rglob("*") if f.is_file())
            summary.append({"camera": folder.name, "photos": count})
        return {"cameras": summary}


if __name__ == "__main__":
    cherrypy.config.update({
        "server.socket_host": "0.0.0.0",
        "server.socket_port": int(os.environ.get("PORT", "8085")),
        "server.max_request_body_size": MAX_UPLOAD_BYTES + 1024 * 1024,
    })
    cherrypy.quickstart(PhotoArchive(), "/")