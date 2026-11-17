import os
import time
import asyncio
import logging
from html import escape
from urllib.parse import urlsplit

import httpx
import uvicorn
from defusedxml import ElementTree as SafeET
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse
from starlette.routing import Route

FEEDS = [u for u in os.environ.get("NEWS_FEEDS", "https://example.org/feed.xml").split(",") if u.strip()]
CACHE_SECONDS = 600
MAX_ITEMS_PER_FEED = 15
FETCH_TIMEOUT = 10.0

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("news-wall")

cache = {"fetched_at": 0.0, "items": [], "errors": []}

PAGE = """<!doctype html>
<html><head><meta charset="utf-8"><title>Team news wall</title>
<meta http-equiv="refresh" content="600">
<style>body{{font-family:sans-serif;max-width:54rem;margin:2rem auto}}
article{{border-bottom:1px solid #eee;padding:.75rem 0}}.src{{color:#777;font-size:.85rem}}</style>
</head><body>
<h1>Team news wall</h1>
{errors}
{items}
</body></html>"""


def text_of(element, tag):
    found = element.find(tag)
    return (found.text or "").strip() if found is not None and found.text else ""


def parse_feed(xml_bytes, source_url):
    root = SafeET.fromstring(xml_bytes)
    channel = root.find("channel")
    if channel is None:
        raise ValueError("not an RSS 2.0 feed")
    source = text_of(channel, "title") or urlsplit(source_url).netloc
    items = []
    for item in channel.findall("item")[:MAX_ITEMS_PER_FEED]:
        items.append({
            "source": source,
            "title": text_of(item, "title") or "(untitled)",
            "link": text_of(item, "link"),
            "summary": text_of(item, "description"),
            "published": text_of(item, "pubDate"),
        })
    return items


async def fetch_feed(client, url):
    response = await client.get(url, timeout=FETCH_TIMEOUT, follow_redirects=True)
    response.raise_for_status()
    return parse_feed(response.content, url)


async def refresh_cache(force=False):
    if not force and time.monotonic() - cache["fetched_at"] < CACHE_SECONDS:
        return
    items, errors = [], []
    async with httpx.AsyncClient(headers={"User-Agent": "news-wall/1.0"}) as client:
        results = await asyncio.gather(*(fetch_feed(client, u) for u in FEEDS), return_exceptions=True)
    for url, result in zip(FEEDS, results):
        if isinstance(result, Exception):
            errors.append(f"{urlsplit(url).netloc}: {type(result).__name__}")
            log.warning("Feed %s failed: %s", url, result)
        else:
            items.extend(result)
    cache.update(fetched_at=time.monotonic(), items=items, errors=errors)


def safe_link(link):
    parts = urlsplit(link)
    return link if parts.scheme in ("http", "https") and parts.netloc else None


def render_item(item):
    link = safe_link(item["link"])
    title = escape(item["title"])
    heading = f'<a href="{escape(link, quote=True)}" rel="noopener">{title}</a>' if link else title
    return (
        f"<article><h2>{heading}</h2>"
        f'<p class="src">{escape(item["source"])} · {escape(item["published"])}</p>'
        f'<div class="summary">{item["summary"]}</div></article>'
    )


async def wall(request: Request):
    await refresh_cache()
    errors = ""
    if cache["errors"]:
        errors = "<p>Some feeds could not be loaded: " + escape(", ".join(cache["errors"])) + "</p>"
    items_html = "\n".join(render_item(i) for i in cache["items"]) or "<p>No news yet.</p>"
    return HTMLResponse(PAGE.format(errors=errors, items=items_html))


async def api_items(request: Request):
    await refresh_cache()
    return JSONResponse({"items": cache["items"], "errors": cache["errors"]})


async def force_refresh(request: Request):
    await refresh_cache(force=True)
    return JSONResponse({"items": len(cache["items"]), "errors": cache["errors"]})


async def health(request: Request):
    return JSONResponse({"status": "ok", "feeds": len(FEEDS)})


app = Starlette(routes=[
    Route("/", wall),
    Route("/api/items", api_items),
    Route("/api/refresh", force_refresh, methods=["POST"]),
    Route("/health", health),
])

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", "8000")))