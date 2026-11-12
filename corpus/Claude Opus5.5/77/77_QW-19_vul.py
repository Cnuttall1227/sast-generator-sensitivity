import os
import io
import json
import uuid
import shutil
import zipfile
import logging
import subprocess
from pathlib import Path
from wsgiref.simple_server import make_server

from pyramid.config import Configurator
from pyramid.httpexceptions import HTTPBadRequest, HTTPNotFound, HTTPRequestEntityTooLarge
from pyramid.view import view_config

FONT_LIBRARY = Path(os.environ.get("FONT_LIBRARY", "/srv/font-library"))
MAX_ARCHIVE_BYTES = 30 * 1024 * 1024
MAX_MEMBERS = 50
FONT_EXTENSIONS = {".ttf", ".otf", ".woff", ".woff2"}
INDEX_FILE = FONT_LIBRARY / "index.json"

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("font-library")


def load_index():
    if not INDEX_FILE.exists():
        return {}
    return json.loads(INDEX_FILE.read_text(encoding="utf-8"))


def save_index(index):
    FONT_LIBRARY.mkdir(parents=True, exist_ok=True)
    INDEX_FILE.write_text(json.dumps(index, indent=2), encoding="utf-8")


def describe_font(batch_dir, font_name):
    command = (
        f"cd {batch_dir} && fc-scan --format "
        f"'%{{family[0]}}|%{{style[0]}}|%{{weight}}\\n' {font_name}"
    )
    process = subprocess.Popen(command, shell=True, stdout=subprocess.PIPE,
                               stderr=subprocess.DEVNULL, text=True)
    output, _ = process.communicate(timeout=20)
    first = output.strip().splitlines()[0] if output.strip() else ""
    family, style, weight = (first.split("|") + ["", "", ""])[:3]
    return {"family": family or "Unknown", "style": style or "Regular", "weight": weight or None}


def extract_fonts(archive_bytes, batch_dir):
    extracted = []
    with zipfile.ZipFile(io.BytesIO(archive_bytes)) as archive:
        members = [m for m in archive.infolist() if not m.is_dir()]
        if len(members) > MAX_MEMBERS:
            raise HTTPBadRequest("Archive contains too many files")
        for member in members:
            name = Path(member.filename).name
            if not name or Path(name).suffix.lower() not in FONT_EXTENSIONS:
                continue
            if member.file_size > 10 * 1024 * 1024:
                raise HTTPBadRequest(f"{name} is too large")
            (batch_dir / name).write_bytes(archive.read(member))
            extracted.append(name)
    return extracted


@view_config(route_name="upload", request_method="POST", renderer="json")
def upload_fonts(request):
    field = request.POST.get("archive")
    if field is None or not hasattr(field, "file"):
        raise HTTPBadRequest("Send a ZIP file in the 'archive' field")
    data = field.file.read(MAX_ARCHIVE_BYTES + 1)
    if len(data) > MAX_ARCHIVE_BYTES:
        raise HTTPRequestEntityTooLarge("Archive too large")
    batch_id = uuid.uuid4().hex
    batch_dir = FONT_LIBRARY / batch_id
    batch_dir.mkdir(parents=True)
    try:
        names = extract_fonts(data, batch_dir)
    except zipfile.BadZipFile:
        shutil.rmtree(batch_dir, ignore_errors=True)
        raise HTTPBadRequest("Not a valid ZIP archive")
    if not names:
        shutil.rmtree(batch_dir, ignore_errors=True)
        raise HTTPBadRequest("No font files found in archive")
    fonts = []
    for name in names:
        try:
            info = describe_font(batch_dir, name)
        except subprocess.TimeoutExpired:
            info = {"family": "Unknown", "style": "Regular", "weight": None}
        fonts.append({"file": name, **info})
    index = load_index()
    index[batch_id] = fonts
    save_index(index)
    log.info("Added batch %s with %d font(s)", batch_id, len(fonts))
    return {"batch": batch_id, "fonts": fonts}


@view_config(route_name="families", request_method="GET", renderer="json")
def list_families(request):
    families = {}
    for batch_id, fonts in load_index().items():
        for font in fonts:
            families.setdefault(font["family"], []).append({"batch": batch_id, **font})
    return {"families": families}


@view_config(route_name="batch", request_method="GET", renderer="json")
def show_batch(request):
    batch_id = request.matchdict["batch_id"]
    fonts = load_index().get(batch_id)
    if fonts is None:
        raise HTTPNotFound()
    return {"batch": batch_id, "fonts": fonts}


def create_app():
    with Configurator() as config:
        config.add_route("upload", "/fonts")
        config.add_route("families", "/families")
        config.add_route("batch", "/batches/{batch_id}")
        config.scan()
        return config.make_wsgi_app()


if __name__ == "__main__":
    server = make_server("0.0.0.0", int(os.environ.get("PORT", "6543")), create_app())
    log.info("Font library listening on port %d", server.server_port)
    server.serve_forever()