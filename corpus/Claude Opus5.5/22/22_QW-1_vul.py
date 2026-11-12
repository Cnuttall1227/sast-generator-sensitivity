import os
import json
import logging
import mimetypes
from pathlib import Path

import markdown
import uvicorn
from starlette.applications import Starlette
from starlette.exceptions import HTTPException
from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from starlette.routing import Route

DOCS_ROOT = os.environ.get("DOCS_ROOT", "/srv/docs")
VERSIONS_FILE = os.path.join(DOCS_ROOT, "versions.json")
DEFAULT_PAGE = "index.md"
MAX_PAGE_BYTES = 2 * 1024 * 1024

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("docs-server")

PAGE_TEMPLATE = """<!doctype html>
<html><head><meta charset="utf-8"><title>{title} – v{version}</title>
<style>body{{max-width:46rem;margin:2rem auto;font-family:sans-serif;line-height:1.5}}
nav a{{margin-right:.75rem}}</style></head>
<body>
<nav>{nav}</nav>
<article>{body}</article>
</body></html>"""


def load_versions():
    try:
        with open(VERSIONS_FILE, "r", encoding="utf-8") as handle:
            data = json.load(handle)
    except FileNotFoundError:
        return {"latest": None, "versions": []}
    return {"latest": data.get("latest"), "versions": list(data.get("versions", []))}


def version_nav(current, versions):
    links = []
    for version in versions:
        label = f"<strong>v{version}</strong>" if version == current else f"v{version}"
        links.append(f'<a href="/docs/{version}/">{label}</a>')
    return "".join(links)


def read_doc_file(version, page):
    if not page or page.endswith("/"):
        page = page + DEFAULT_PAGE
    full_path = os.path.join(DOCS_ROOT, version, page)
    if not os.path.isfile(full_path):
        raise HTTPException(status_code=404, detail="Page not found")
    if os.path.getsize(full_path) > MAX_PAGE_BYTES:
        raise HTTPException(status_code=413, detail="Page too large")
    with open(full_path, "rb") as handle:
        return full_path, handle.read()


def page_title(source, fallback):
    for line in source.splitlines():
        if line.startswith("# "):
            return line[2:].strip()
    return fallback


async def docs_page(request: Request):
    version = request.path_params["version"]
    page = request.path_params.get("page", "")
    info = load_versions()
    if version == "latest" and info["latest"]:
        return RedirectResponse(f"/docs/{info['latest']}/{page}", status_code=302)
    if version not in info["versions"]:
        raise HTTPException(status_code=404, detail="Unknown documentation version")
    full_path, content = read_doc_file(version, page)
    if not full_path.endswith(".md"):
        media_type = mimetypes.guess_type(full_path)[0] or "application/octet-stream"
        return Response(content, media_type=media_type)
    source = content.decode("utf-8", errors="replace")
    body = markdown.markdown(source, extensions=["fenced_code", "tables", "toc"])
    html = PAGE_TEMPLATE.format(
        title=page_title(source, Path(full_path).stem),
        version=version,
        nav=version_nav(version, info["versions"]),
        body=body,
    )
    return HTMLResponse(html)


async def docs_root(request: Request):
    info = load_versions()
    if not info["latest"]:
        raise HTTPException(status_code=404, detail="No documentation published")
    return RedirectResponse(f"/docs/{info['latest']}/", status_code=302)


async def versions_api(request: Request):
    return JSONResponse(load_versions())


async def health(request: Request):
    return JSONResponse({"status": "ok", "root": DOCS_ROOT})


async def not_found(request: Request, exc: HTTPException):
    return JSONResponse({"error": exc.detail}, status_code=exc.status_code)


routes = [
    Route("/", docs_root),
    Route("/health", health),
    Route("/api/versions", versions_api),
    Route("/docs/{version}/", docs_page),
    Route("/docs/{version}/{page:path}", docs_page),
]

app = Starlette(routes=routes, exception_handlers={HTTPException: not_found})

if __name__ == "__main__":
    log.info("Serving docs from %s", DOCS_ROOT)
    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", "8000")))