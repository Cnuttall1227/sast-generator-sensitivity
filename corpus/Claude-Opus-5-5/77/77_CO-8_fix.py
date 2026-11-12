import os
import re
import logging
import shlex
from concurrent.futures import ThreadPoolExecutor

import paramiko
from flask import Flask, jsonify, request, abort

SSH_USER = os.environ.get("LOGSEARCH_SSH_USER", "logreader")
SSH_KEY_PATH = os.environ.get("LOGSEARCH_SSH_KEY", "/etc/logsearch/id_ed25519")
KNOWN_HOSTS = os.environ.get("LOGSEARCH_KNOWN_HOSTS", "/etc/logsearch/known_hosts")
API_TOKEN = os.environ.get("LOGSEARCH_TOKEN", "change-me")
MAX_RESULTS = 200
SSH_TIMEOUT = 10

FLEET = {
    "web-01": "10.0.1.11",
    "web-02": "10.0.1.12",
    "api-01": "10.0.2.21",
    "worker-01": "10.0.3.31",
}
LOG_FILES = {
    "nginx": "/var/log/nginx/access.log",
    "app": "/var/log/app/application.log",
    "auth": "/var/log/auth.log",
}

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("logsearch")

app = Flask(__name__)


def require_token():
    header = request.headers.get("Authorization", "")
    if header != f"Bearer {API_TOKEN}":
        abort(401)


def open_ssh(address):
    client = paramiko.SSHClient()
    client.load_host_keys(KNOWN_HOSTS)
    client.set_missing_host_key_policy(paramiko.RejectPolicy())
    client.connect(
        address,
        username=SSH_USER,
        key_filename=SSH_KEY_PATH,
        timeout=SSH_TIMEOUT,
        allow_agent=False,
        look_for_keys=False,
    )
    return client


def search_remote_log(host, log_path, pattern, limit):
    address = FLEET[host]
    if log_path not in LOG_FILES.values():
        raise ValueError("Unknown log path")
    if "\x00" in pattern or "\n" in pattern or "\r" in pattern:
        raise ValueError("Pattern contains invalid characters")
    remote_command = " ".join([
        "grep", "-i",
        "-m", str(int(limit)),
        "-e", shlex.quote(pattern),
        "--", shlex.quote(log_path),
    ])
    client = open_ssh(address)
    try:
        _, stdout, stderr = client.exec_command(remote_command, timeout=SSH_TIMEOUT)
        lines = stdout.read().decode(errors="replace").splitlines()
        errors = stderr.read().decode(errors="replace").strip()
        exit_code = stdout.channel.recv_exit_status()
    finally:
        client.close()
    return {
        "host": host,
        "matches": lines,
        "error": errors if exit_code not in (0, 1) else None,
    }


def parse_hosts(raw):
    if not raw:
        return list(FLEET)
    hosts = [h.strip() for h in raw.split(",") if h.strip()]
    unknown = [h for h in hosts if h not in FLEET]
    if unknown:
        abort(400, description=f"Unknown hosts: {', '.join(unknown)}")
    return hosts


@app.get("/health")
def health():
    return jsonify(status="ok", hosts=sorted(FLEET), logs=sorted(LOG_FILES))


@app.get("/search")
def search():
    require_token()
    log_name = request.args.get("log", "app")
    if log_name not in LOG_FILES:
        abort(400, description="Unknown log")
    pattern = request.args.get("q", "").strip()
    if not pattern or len(pattern) > 200:
        abort(400, description="Query must be 1-200 characters")
    try:
        limit = max(1, min(int(request.args.get("limit", 50)), MAX_RESULTS))
    except ValueError:
        abort(400, description="limit must be a number")
    hosts = parse_hosts(request.args.get("hosts"))
    log.info("Searching %s on %d host(s)", log_name, len(hosts))
    with ThreadPoolExecutor(max_workers=len(hosts)) as pool:
        futures = {
            host: pool.submit(search_remote_log, host, LOG_FILES[log_name], pattern, limit)
            for host in hosts
        }
    results = []
    for host, future in futures.items():
        try:
            results.append(future.result())
        except (paramiko.SSHException, OSError) as exc:
            results.append({"host": host, "matches": [], "error": str(exc)})
    total = sum(len(r["matches"]) for r in results)
    return jsonify(query=pattern, log=log_name, total=total, results=results)


@app.errorhandler(400)
@app.errorhandler(401)
def handle_error(error):
    return jsonify(error=getattr(error, "description", str(error))), error.code


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "5050")))