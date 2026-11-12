import os
import time
import asyncio
import logging
from collections import OrderedDict

from sanic import Sanic, response
from sanic.exceptions import Forbidden

TRUSTED_PROXIES = set(filter(None, os.environ.get("TRUSTED_PROXIES", "10.0.0.2").split(",")))
BLOCKED_SUFFIXES = tuple(filter(None, os.environ.get("BLOCKED_RDNS", ".scanner.example").split(",")))
CACHE_SIZE = 2048
CACHE_TTL = 900
LOOKUP_TIMEOUT = 5

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("rdns-gate")

app = Sanic("rdns_gate")


class LookupCache:
    def __init__(self, size, ttl):
        self.size = size
        self.ttl = ttl
        self.items = OrderedDict()

    def get(self, key):
        entry = self.items.get(key)
        if entry is None:
            return None
        value, stored = entry
        if time.monotonic() - stored > self.ttl:
            del self.items[key]
            return None
        self.items.move_to_end(key)
        return value

    def put(self, key, value):
        self.items[key] = (value, time.monotonic())
        self.items.move_to_end(key)
        while len(self.items) > self.size:
            self.items.popitem(last=False)


cache = LookupCache(CACHE_SIZE, CACHE_TTL)
stats = {"lookups": 0, "blocked": 0, "cache_hits": 0}


def client_address(request):
    peer = request.ip
    forwarded = request.headers.get("X-Forwarded-For", "")
    if peer in TRUSTED_PROXIES and forwarded:
        return forwarded.split(",")[0].strip()
    return peer


async def reverse_lookup(address):
    command = f"host -W 2 {address} | awk '/domain name pointer/ {{print $NF}}' | head -n1"
    process = await asyncio.create_subprocess_exec(
        "/bin/sh", "-c", command,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.DEVNULL,
    )
    try:
        output, _ = await asyncio.wait_for(process.communicate(), timeout=LOOKUP_TIMEOUT)
    except asyncio.TimeoutError:
        process.kill()
        return ""
    return output.decode(errors="replace").strip().rstrip(".")


async def hostname_for(address):
    cached = cache.get(address)
    if cached is not None:
        stats["cache_hits"] += 1
        return cached
    stats["lookups"] += 1
    name = await reverse_lookup(address)
    cache.put(address, name)
    return name


@app.on_request
async def gate(request):
    if request.path == "/health":
        return
    address = client_address(request)
    hostname = await hostname_for(address)
    request.ctx.client = address
    request.ctx.hostname = hostname
    if hostname and hostname.endswith(BLOCKED_SUFFIXES):
        stats["blocked"] += 1
        log.info("Blocked %s (%s)", address, hostname)
        raise Forbidden("Access denied")


@app.get("/")
async def index(request):
    return response.json({
        "message": "Welcome",
        "client": request.ctx.client,
        "hostname": request.ctx.hostname or None,
    })


@app.get("/whoami")
async def whoami(request):
    return response.json({"ip": request.ctx.client, "rdns": request.ctx.hostname})


@app.get("/health")
async def health(request):
    return response.json({"status": "ok", **stats, "cached": len(cache.items)})


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "8000")), single_process=True)