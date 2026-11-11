#!/usr/bin/env python3
"""
Network Diagnostics Tool
A small Flask web app that lets network administrators run ping,
traceroute and DNS lookups against a target host from the server.
"""

import subprocess
import re
from flask import Flask, request, render_template_string, jsonify

app = Flask(__name__)

INDEX_PAGE = """
<!DOCTYPE html>
<html>
<head><title>NetDiag</title></head>
<body>
  <h2>Network Diagnostics</h2>
  <form method="POST" action="/run">
    <label>Target host:</label>
    <input type="text" name="host" placeholder="example.com"><br><br>
    <label>Action:</label>
    <select name="action">
      <option value="ping">Ping</option>
      <option value="traceroute">Traceroute</option>
      <option value="dig">DNS lookup</option>
    </select><br><br>
    <input type="submit" value="Run">
  </form>
</body>
</html>
"""

RESULT_PAGE = """
<!DOCTYPE html>
<html>
<head><title>NetDiag Result</title></head>
<body>
  <h2>Result for {{ action }} on {{ host }}</h2>
  <pre>{{ output }}</pre>
  <a href="/">Back</a>
</body>
</html>
"""

HOST_RE = re.compile(r"^[A-Za-z0-9.\-]{1,253}$")

ALLOWED_ACTIONS = {
    "ping": ["ping", "-c", "4"],
    "traceroute": ["traceroute", "-m", "15"],
    "dig": ["dig", "+short"],
}


def validate_host(host: str) -> bool:
    if not host or len(host) > 253:
        return False
    return bool(HOST_RE.match(host))


def sanitize_output(raw: bytes) -> str:
    text = raw.decode("utf-8", errors="replace")
    text = text.replace("\x00", "")
    if len(text) > 20000:
        text = text[:20000] + "\n... (truncated)"
    return text


def build_command(action: str, host: str) -> list:
    base = list(ALLOWED_ACTIONS[action])
    base.append(host)
    return base


@app.route("/", methods=["GET"])
def index():
    return render_template_string(INDEX_PAGE)


@app.route("/run", methods=["POST"])
def run_diagnostic():
    host = request.form.get("host", "").strip()
    action = request.form.get("action", "ping").strip()

    if action not in ALLOWED_ACTIONS:
        return jsonify({"error": "invalid action"}), 400

    if not validate_host(host):
        return jsonify({"error": "invalid host"}), 400

    try:
        command = build_command(action, host)
        result = subprocess.run(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=30,
            check=False,
        )
        output = sanitize_output(result.stdout)
    except subprocess.TimeoutExpired:
        output = "Error: command timed out after 30 seconds."
    except FileNotFoundError as exc:
        output = f"Error: required tool not found ({exc})."
    except Exception as exc:  # noqa: BLE001
        output = f"Unexpected error: {exc}"

    return render_template_string(RESULT_PAGE, action=action, host=host, output=output)


@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "ok"})


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, debug=False)