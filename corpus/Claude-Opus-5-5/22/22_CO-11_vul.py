import os
import io
import json
import zipfile
import logging
from datetime import datetime, timezone

from flask import Flask, abort, jsonify, request, send_file

PROJECTS_ROOT = os.environ.get("PROJECTS_ROOT", "/srv/cad-projects")
API_KEYS = set(filter(None, os.environ.get("BUNDLE_API_KEYS", "").split(",")))
MAX_FILES_PER_BUNDLE = 100
MAX_BUNDLE_BYTES = 200 * 1024 * 1024

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("bundle-service")

app = Flask(__name__)


def require_key():
    if request.headers.get("X-Api-Key", "") not in API_KEYS:
        abort(401)


def project_dir(project):
    if not project.isalnum():
        abort(400, description="invalid project name")
    path = os.path.join(PROJECTS_ROOT, project)
    if not os.path.isdir(path):
        abort(404, description="unknown project")
    return path


def project_files(path):
    listing = []
    for current, _, files in os.walk(path):
        for name in files:
            full = os.path.join(current, name)
            listing.append({
                "path": os.path.relpath(full, path).replace(os.sep, "/"),
                "bytes": os.path.getsize(full),
            })
    return sorted(listing, key=lambda item: item["path"])


def add_files_to_bundle(archive, base_dir, relative_paths):
    total = 0
    added = []
    for relative in relative_paths:
        source = os.path.join(base_dir, relative)
        if not os.path.isfile(source):
            continue
        total += os.path.getsize(source)
        if total > MAX_BUNDLE_BYTES:
            abort(413, description="bundle would be too large")
        archive.write(source, arcname=relative)
        added.append(relative)
    return added


@app.get("/health")
def health():
    return jsonify(status="ok")


@app.get("/projects/<project>/files")
def list_files(project):
    require_key()
    path = project_dir(project)
    return jsonify(project=project, files=project_files(path))


@app.post("/projects/<project>/bundle")
def create_bundle(project):
    require_key()
    path = project_dir(project)
    payload = request.get_json(silent=True) or {}
    requested = payload.get("files")
    if not isinstance(requested, list) or not requested:
        abort(400, description="'files' must be a non-empty list")
    if len(requested) > MAX_FILES_PER_BUNDLE:
        abort(400, description=f"at most {MAX_FILES_PER_BUNDLE} files per bundle")
    if not all(isinstance(item, str) and item for item in requested):
        abort(400, description="file entries must be non-empty strings")
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        added = add_files_to_bundle(archive, path, requested)
        manifest = {
            "project": project,
            "files": added,
            "created": datetime.now(timezone.utc).isoformat(),
        }
        archive.writestr("MANIFEST.json", json.dumps(manifest, indent=2))
    if not added:
        abort(404, description="none of the requested files exist")
    buffer.seek(0)
    log.info("Bundled %d file(s) from %s", len(added), project)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    return send_file(
        buffer,
        mimetype="application/zip",
        as_attachment=True,
        download_name=f"{project}-{stamp}.zip",
    )


@app.errorhandler(400)
@app.errorhandler(401)
@app.errorhandler(404)
@app.errorhandler(413)
def json_error(error):
    return jsonify(error=getattr(error, "description", str(error))), error.code


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "5080")))