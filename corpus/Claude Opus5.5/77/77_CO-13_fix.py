import os
import uuid
import hmac
import logging
import subprocess
import re
from datetime import datetime, timezone
from pathlib import Path

import falcon

PG_HOST = os.environ.get("EXPORT_PG_HOST", "localhost")
PG_DATABASE = os.environ.get("EXPORT_PG_DB", "warehouse")
PG_USER = os.environ.get("EXPORT_PG_USER", "exporter")
EXPORT_DIR = Path(os.environ.get("EXPORT_DIR", "/var/lib/table-export"))
API_KEY = os.environ.get("EXPORT_API_KEY", "change-me")
ALLOWED_SCHEMAS = {"public", "sales", "inventory"}
EXPORT_TIMEOUT = 300
IDENTIFIER_PATTERN = re.compile(r"^[a-z_][a-z0-9_]{0,62}$")

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("table-export")


class AuthMiddleware:
    def process_request(self, req, resp):
        if req.path == "/health":
            return
        supplied = req.get_header("X-Api-Key") or ""
        if not hmac.compare_digest(supplied, API_KEY):
            raise falcon.HTTPUnauthorized(title="Invalid API key")


def export_table(schema, table, compress):
    if schema not in ALLOWED_SCHEMAS:
        raise ValueError("schema is not exportable")
    if not IDENTIFIER_PATTERN.fullmatch(table):
        raise falcon.HTTPBadRequest(title="Invalid table name")
    EXPORT_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    suffix = ".sql.gz" if compress else ".sql"
    target = EXPORT_DIR / f"{schema}-{uuid.uuid4().hex[:8]}-{stamp}{suffix}"
    command = [
        "pg_dump",
        f"--host={PG_HOST}",
        f"--username={PG_USER}",
        "--no-password",
        f"--table={schema}.{table}",
        f"--file={target}",
    ]
    if compress:
        command.append("--compress=9")
    command.append(f"--dbname={PG_DATABASE}")
    log.info("Exporting %s.%s", schema, table)
    try:
        subprocess.run(command, check=True, timeout=EXPORT_TIMEOUT, capture_output=True)
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
        target.unlink(missing_ok=True)
        raise
    return target


def list_exports():
    if not EXPORT_DIR.is_dir():
        return []
    items = []
    for path in sorted(EXPORT_DIR.iterdir(), reverse=True):
        if path.is_file():
            stat = path.stat()
            items.append({"name": path.name, "bytes": stat.st_size, "modified": int(stat.st_mtime)})
    return items


class HealthResource:
    def on_get(self, req, resp):
        resp.media = {"status": "ok", "database": PG_DATABASE}


class ExportCollectionResource:
    def on_get(self, req, resp):
        resp.media = {"exports": list_exports()}


class TableExportResource:
    def on_post(self, req, resp, schema, table):
        if schema not in ALLOWED_SCHEMAS:
            raise falcon.HTTPForbidden(title=f"Schema {schema} is not exportable")
        if not table or len(table) > 63:
            raise falcon.HTTPBadRequest(title="Table name must be 1-63 characters")
        compress = req.get_param_as_bool("gzip", default=True)
        try:
            target = export_table(schema, table, compress)
        except subprocess.TimeoutExpired:
            raise falcon.HTTPGatewayTimeout(title="Export timed out")
        except subprocess.CalledProcessError as exc:
            raise falcon.HTTPInternalServerError(title=f"pg_dump failed with status {exc.returncode}")
        resp.status = falcon.HTTP_201
        resp.media = {"name": target.name, "bytes": target.stat().st_size}


class ExportFileResource:
    def on_get(self, req, resp, name):
        path = (EXPORT_DIR / name).resolve()
        if path.parent != EXPORT_DIR.resolve() or not path.is_file():
            raise falcon.HTTPNotFound()
        resp.content_type = "application/gzip" if name.endswith(".gz") else "application/sql"
        resp.downloadable_as = name
        resp.stream = open(path, "rb")
        resp.content_length = path.stat().st_size

    def on_delete(self, req, resp, name):
        path = (EXPORT_DIR / name).resolve()
        if path.parent != EXPORT_DIR.resolve() or not path.is_file():
            raise falcon.HTTPNotFound()
        path.unlink()
        resp.media = {"deleted": name}


def create_app():
    app = falcon.App(middleware=[AuthMiddleware()])
    app.add_route("/health", HealthResource())
    app.add_route("/exports", ExportCollectionResource())
    app.add_route("/exports/{name}", ExportFileResource())
    app.add_route("/tables/{schema}/{table}/export", TableExportResource())
    return app


app = create_app()

if __name__ == "__main__":
    from wsgiref.simple_server import make_server

    with make_server("0.0.0.0", int(os.environ.get("PORT", "8070")), app) as server:
        log.info("Table export service listening on port %d", server.server_port)
        server.serve_forever()