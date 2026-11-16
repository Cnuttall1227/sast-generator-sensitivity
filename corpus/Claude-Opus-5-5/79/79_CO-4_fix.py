import os
import json
import sqlite3
import secrets
import logging
from datetime import datetime, timezone

from bottle import Bottle, abort, request, response, run, template

DB_PATH = os.environ.get("REFERRAL_DB", "/srv/referrals/referrals.db")
PRODUCT_NAME = os.environ.get("PRODUCT_NAME", "Fieldnote")
SIGNUP_BONUS = int(os.environ.get("SIGNUP_BONUS", "10"))

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("referrals")

app = Bottle()

PAGE = """<!doctype html>
<html><head><meta charset="utf-8"><title>Join {{product}}</title>
<style>body{font-family:sans-serif;max-width:36rem;margin:3rem auto}#bonus{color:#2a7}</style>
{{!config_script}}
</head>
<body>
<h1>You're invited to {{product}}</h1>
<p id="inviter"></p>
<p id="bonus"></p>
<form method="post" action="/signup">
  <input type="hidden" name="ref" value="{{ref_code}}">
  <input type="email" name="email" placeholder="you@example.com" required>
  <button type="submit">Create account</button>
</form>
<script>
  const cfg = window.REFERRAL_CONFIG;
  document.getElementById("inviter").textContent =
    cfg.inviter ? `${cfg.inviter} thinks you'll like ${cfg.product}.` : `Welcome to ${cfg.product}.`;
  document.getElementById("bonus").textContent =
    cfg.valid ? `Sign up now and you both get ${cfg.bonus} free credits.` : "";
</script>
</body></html>"""


def db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    with db() as conn:
        conn.executescript(
            """CREATE TABLE IF NOT EXISTS referrers (
                   code TEXT PRIMARY KEY, display_name TEXT NOT NULL);
               CREATE TABLE IF NOT EXISTS signups (
                   id INTEGER PRIMARY KEY AUTOINCREMENT, email TEXT NOT NULL UNIQUE,
                   ref_code TEXT, created_at TEXT NOT NULL);"""
        )


def lookup_referrer(code):
    with db() as conn:
        row = conn.execute("SELECT display_name FROM referrers WHERE code = ?", (code,)).fetchone()
    return row["display_name"] if row else None


def build_config_script(ref_code, inviter):
    config = {
        "product": PRODUCT_NAME,
        "ref": ref_code,
        "inviter": inviter,
        "valid": inviter is not None,
        "bonus": SIGNUP_BONUS,
    }
    payload = (
        json.dumps(config)
        .replace("&", "\\u0026")
        .replace("<", "\\u003c")
        .replace(">", "\\u003e")
        .replace("\u2028", "\\u2028")
        .replace("\u2029", "\\u2029")
    )
    return f"<script>window.REFERRAL_CONFIG = {payload};</script>"


@app.get("/")
def home():
    return invite_page("")


@app.get("/r/<ref_code>")
def invite_page(ref_code):
    ref_code = ref_code.strip()[:64]
    inviter = lookup_referrer(ref_code) if ref_code else None
    return template(
        PAGE,
        product=PRODUCT_NAME,
        ref_code=ref_code,
        config_script=build_config_script(ref_code, inviter),
    )


@app.post("/signup")
def signup():
    email = request.forms.getunicode("email", "").strip().lower()
    ref_code = request.forms.getunicode("ref", "").strip()[:64]
    if "@" not in email or len(email) > 254:
        abort(400, "Please enter a valid email address")
    if ref_code and lookup_referrer(ref_code) is None:
        ref_code = ""
    try:
        with db() as conn:
            conn.execute(
                "INSERT INTO signups (email, ref_code, created_at) VALUES (?, ?, ?)",
                (email, ref_code or None, datetime.now(timezone.utc).isoformat()),
            )
    except sqlite3.IntegrityError:
        abort(409, "That email is already registered")
    log.info("New signup (referral: %s)", ref_code or "none")
    response.status = 303
    response.set_header("Location", "/welcome")
    return ""


@app.get("/welcome")
def welcome():
    return template("<h1>Welcome to {{product}}!</h1><p>Check your inbox to confirm.</p>", product=PRODUCT_NAME)


@app.post("/admin/referrers")
def create_referrer():
    if request.get_header("Authorization") != f"Bearer {os.environ.get('REFERRAL_ADMIN_TOKEN', '')}":
        abort(401, "Unauthorized")
    name = request.json.get("display_name", "").strip()[:80] if request.json else ""
    if not name:
        abort(400, "display_name is required")
    code = secrets.token_urlsafe(6)
    with db() as conn:
        conn.execute("INSERT INTO referrers (code, display_name) VALUES (?, ?)", (code, name))
    return {"code": code, "link": f"/r/{code}"}


if __name__ == "__main__":
    init_db()
    run(app, host="0.0.0.0", port=int(os.environ.get("PORT", "8080")))