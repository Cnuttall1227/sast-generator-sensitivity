import os
import json
import time
import signal
import logging
import subprocess
import re
import ipaddress
from datetime import datetime, timezone

import redis

REDIS_URL = os.environ.get("REDIS_URL", "redis://localhost:6379/0")
QUEUE_KEY = "dnscheck:jobs"
RESULT_PREFIX = "dnscheck:result:"
RESULT_TTL_SECONDS = 3600
ALLOWED_RECORD_TYPES = {"A", "AAAA", "MX", "TXT", "NS", "CNAME", "SOA"}
DIG_TIMEOUT_SECONDS = 15
DOMAIN_PATTERN = re.compile(
    r"^(?=.{1,253}$)(?:[A-Za-z0-9_](?:[A-Za-z0-9_-]{0,61}[A-Za-z0-9])?\.)*"
    r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?$"
)


logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("dnscheck-worker")


class Worker:
    def __init__(self, client):
        self.client = client
        self.running = True
        self.processed = 0
        signal.signal(signal.SIGTERM, self.stop)
        signal.signal(signal.SIGINT, self.stop)

    def stop(self, *_):
        log.info("Stop requested, finishing current job")
        self.running = False

    def fetch_job(self):
        item = self.client.blpop(QUEUE_KEY, timeout=5)
        if item is None:
            return None
        _, raw = item
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            log.warning("Discarding malformed job payload")
            return None

    def store_result(self, job_id, result):
        key = RESULT_PREFIX + job_id
        self.client.set(key, json.dumps(result), ex=RESULT_TTL_SECONDS)

    def run(self):
        log.info("Worker listening on %s", QUEUE_KEY)
        while self.running:
            job = self.fetch_job()
            if job is None:
                continue
            job_id = str(job.get("id", "")) or f"anon-{int(time.time() * 1000)}"
            try:
                result = handle_job(job)
            except ValueError as exc:
                result = {"status": "rejected", "error": str(exc)}
            except Exception as exc:
                log.exception("Job %s failed", job_id)
                result = {"status": "error", "error": str(exc)}
            result["finished_at"] = datetime.now(timezone.utc).isoformat()
            self.store_result(job_id, result)
            self.processed += 1
        log.info("Worker stopped after %d job(s)", self.processed)


def run_lookup(domain, record_type, resolver):
    if not DOMAIN_PATTERN.fullmatch(domain):
        return None, "invalid domain"
    if record_type not in ALLOWED_RECORD_TYPES:
        return None, "unsupported record type"
    try:
        resolver_ip = str(ipaddress.ip_address(resolver))
    except ValueError:
        return None, "resolver must be an IP address"
    command = [
        "dig", "+short", "+time=3", "+tries=2",
        f"@{resolver_ip}",
        "-q", domain,
        "-t", record_type,
    ]
    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=DIG_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired:
        return None, "lookup timed out"
    if result.returncode != 0:
        return None, result.stderr.strip() or f"dig exited with {result.returncode}"
    return [line for line in result.stdout.splitlines() if line.strip()], None


def handle_job(job):
    domain = str(job.get("domain", "")).strip().rstrip(".")
    if not domain:
        raise ValueError("domain is required")
    record_type = str(job.get("type", "A")).upper()
    if record_type not in ALLOWED_RECORD_TYPES:
        raise ValueError(f"unsupported record type {record_type}")
    resolver = str(job.get("resolver", "1.1.1.1"))
    started = time.monotonic()
    answers, error = run_lookup(domain, record_type, resolver)
    elapsed_ms = int((time.monotonic() - started) * 1000)
    if error:
        return {"status": "failed", "domain": domain, "type": record_type, "error": error}
    return {
        "status": "ok",
        "domain": domain,
        "type": record_type,
        "resolver": resolver,
        "answers": answers,
        "elapsed_ms": elapsed_ms,
    }


def main():
    client = redis.Redis.from_url(REDIS_URL, decode_responses=True)
    client.ping()
    Worker(client).run()


if __name__ == "__main__":
    main()