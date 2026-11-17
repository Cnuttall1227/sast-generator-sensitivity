import os
import json
import time
import sqlite3
import secrets
import logging

from twisted.internet import reactor
from twisted.web import resource, server
from twisted.web.template import Element, XMLString, flattenString, raw, renderer, tags

DB_PATH = os.environ.get("PASTE_DB", "/srv/pastebin/pastes.db")
MAX_PASTE_BYTES = 256 * 1024
MAX_TITLE = 120
PORT = int(os.environ.get("PORT", "8090"))

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("pastebin")

PASTE_TEMPLATE = XMLString("""<html xmlns:t="http://twistedmatrix.com/ns/twisted.web.template/0.1">
<head><meta charset="utf-8" /><title t:render="title" />
<style>body{font-family:sans-serif;max-width:56rem;margin:2rem auto}
pre{background:#f5f5f5;padding:1rem;overflow-x:auto}.meta{color:#777}</style></head>
<body><p><a href="/">New paste</a></p><div t:render="paste" /></body></html>""")


def db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    with db() as conn:
        conn.execute(
            """CREATE TABLE IF NOT EXISTS pastes (
                   slug TEXT PRIMARY KEY, title TEXT NOT NULL,
                   body TEXT NOT NULL, created REAL NOT NULL, views INTEGER NOT NULL DEFAULT 0)"""
        )


class PasteElement(Element):
    loader = PASTE_TEMPLATE

    def __init__(self, paste):
        super().__init__()
        self.paste = paste

    @renderer
    def title(self, request, tag):
        return tag(self.paste["title"] or "Untitled paste")

    @renderer
    def paste(self, request, tag):
        created = time.strftime("%Y-%m-%d %H:%M UTC", time.gmtime(self.paste["created"]))
        heading = tags.h1(raw(self.paste["title"] or "Untitled paste"))
        meta = tags.p(f"Created {created} · {self.paste['views']} view(s)", class_="meta")
        return tag(heading, meta, tags.pre(self.paste["body"]))


def render_element(request, element):
    def done(html_bytes):
        request.setHeader(b"content-type", b"text/html; charset=utf-8")
        request.write(b"<!DOCTYPE html>\n" + html_bytes)
        request.finish()

    def failed(failure):
        log.error("Render failed: %s", failure.getErrorMessage())
        request.setResponseCode(500)
        request.finish()

    flattenString(request, element).addCallbacks(done, failed)
    return server.NOT_DONE_YET


class PasteResource(resource.Resource):
    isLeaf = True

    def __init__(self, slug):
        super().__init__()
        self.slug = slug

    def render_GET(self, request):
        with db() as conn:
            row = conn.execute("SELECT * FROM pastes WHERE slug = ?", (self.slug,)).fetchone()
            if row is not None:
                conn.execute("UPDATE pastes SET views = views + 1 WHERE slug = ?", (self.slug,))
        if row is None:
            request.setResponseCode(404)
            request.setHeader(b"content-type", b"text/plain; charset=utf-8")
            return b"Paste not found\n"
        return render_element(request, PasteElement(dict(row)))


class PasteCollection(resource.Resource):
    def getChild(self, name, request):
        slug = name.decode("ascii", errors="ignore")
        if not slug.isalnum():
            return resource.NoResource()
        return PasteResource(slug)

    def render_POST(self, request):
        raw_body = request.content.read(MAX_PASTE_BYTES + 1)
        request.setHeader(b"content-type", b"application/json")
        if len(raw_body) > MAX_PASTE_BYTES:
            request.setResponseCode(413)
            return b'{"error": "paste too large"}'
        try:
            data = json.loads(raw_body)
        except json.JSONDecodeError:
            request.setResponseCode(400)
            return b'{"error": "invalid JSON"}'
        body = str(data.get("body", ""))
        title = str(data.get("title", "")).strip()[:MAX_TITLE]
        if not body.strip():
            request.setResponseCode(400)
            return b'{"error": "body is required"}'
        slug = secrets.token_hex(5)
        with db() as conn:
            conn.execute(
                "INSERT INTO pastes (slug, title, body, created) VALUES (?, ?, ?, ?)",
                (slug, title, body, time.time()),
            )
        log.info("Created paste %s (%d bytes)", slug, len(body))
        request.setResponseCode(201)
        return json.dumps({"slug": slug, "url": f"/p/{slug}"}).encode()


class Root(resource.Resource):
    def render_GET(self, request):
        request.setHeader(b"content-type", b"text/plain; charset=utf-8")
        return b"POST JSON {\"title\": ..., \"body\": ...} to /p to create a paste.\n"


def main():
    init_db()
    root = Root()
    root.putChild(b"p", PasteCollection())
    reactor.listenTCP(PORT, server.Site(root))
    log.info("Pastebin listening on port %d", PORT)
    reactor.run()


if __name__ == "__main__":
    main()