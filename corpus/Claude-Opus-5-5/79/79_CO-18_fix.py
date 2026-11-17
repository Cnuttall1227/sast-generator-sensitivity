import os
import html
import secrets
import logging
from urllib.parse import urlencode

import httpx
import uvicorn
from blacksheep import Application, Request, Response, redirect
from blacksheep.server.responses import html as html_response

CLIENT_ID = os.environ.get("OAUTH_CLIENT_ID", "")
CLIENT_SECRET = os.environ.get("OAUTH_CLIENT_SECRET", "")
AUTHORIZE_URL = os.environ.get("OAUTH_AUTHORIZE_URL", "https://auth.example.com/oauth/authorize")
TOKEN_URL = os.environ.get("OAUTH_TOKEN_URL", "https://auth.example.com/oauth/token")
USERINFO_URL = os.environ.get("OAUTH_USERINFO_URL", "https://auth.example.com/oauth/userinfo")
REDIRECT_URI = os.environ.get("OAUTH_REDIRECT_URI", "http://localhost:8000/auth/callback")
STATE_COOKIE = "oauth_state"

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("sso-portal")

app = Application()
sessions = {}

PAGE = """<!doctype html>
<html><head><meta charset="utf-8"><title>{title}</title>
<style>body{{font-family:sans-serif;max-width:34rem;margin:4rem auto;text-align:center}}
.box{{border:1px solid #ddd;border-radius:8px;padding:2rem}}.err{{color:#a00}}</style>
</head><body><div class="box">{body}</div></body></html>"""


def page(title, body, status=200):
    response = html_response(PAGE.format(title=html.escape(title), body=body))
    response.status = status
    return response


def render_oauth_error(error_code, description):
    friendly = {
        "access_denied": "You cancelled the sign-in.",
        "invalid_scope": "The app asked for permissions it isn't allowed to have.",
        "server_error": "The sign-in service had a problem.",
    }.get(error_code, "Sign-in could not be completed.")
    description = (description or "").strip()
    if len(description) > 300:
        description = description[:300] + "…"
    details = f"<p class='err'>{html.escape(description)}</p>" if description else ""
    body = (
        f"<h1>Sign-in failed</h1><p>{html.escape(friendly)}</p>{details}"
        f"<p><small>Error code: {html.escape(error_code or 'unknown')}</small></p>"
        "<p><a href='/login'>Try again</a></p>"
    )
    return page("Sign-in failed", body, status=400)


def current_user(request: Request):
    session_id = request.cookies.get("portal_session")
    return sessions.get(session_id) if session_id else None


@app.router.get("/")
async def home(request: Request):
    user = current_user(request)
    if user is None:
        return page("Staff portal", "<h1>Staff portal</h1><p><a href='/login'>Sign in with SSO</a></p>")
    name = html.escape(user.get("name") or user.get("email") or "there")
    return page("Staff portal", f"<h1>Welcome, {name}</h1><p><a href='/logout'>Sign out</a></p>")


@app.router.get("/login")
async def login(request: Request):
    state = secrets.token_urlsafe(24)
    query = urlencode({
        "response_type": "code",
        "client_id": CLIENT_ID,
        "redirect_uri": REDIRECT_URI,
        "scope": "openid profile email",
        "state": state,
    })
    response = redirect(f"{AUTHORIZE_URL}?{query}")
    response.set_cookie_value = None
    response.add_header(b"Set-Cookie", f"{STATE_COOKIE}={state}; HttpOnly; SameSite=Lax; Path=/auth".encode())
    return response


@app.router.get("/auth/callback")
async def callback(request: Request):
    params = request.query
    error = (params.get("error") or [None])[0]
    if error:
        description = (params.get("error_description") or [""])[0]
        log.info("OAuth error returned: %s", error)
        return render_oauth_error(error, description)
    code = (params.get("code") or [""])[0]
    state = (params.get("state") or [""])[0]
    expected = request.cookies.get(STATE_COOKIE)
    if not code or not expected or not secrets.compare_digest(state, expected):
        return render_oauth_error("invalid_state", "")
    async with httpx.AsyncClient(timeout=10) as client:
        token_response = await client.post(TOKEN_URL, data={
            "grant_type": "authorization_code", "code": code, "redirect_uri": REDIRECT_URI,
            "client_id": CLIENT_ID, "client_secret": CLIENT_SECRET,
        })
        if token_response.status_code != 200:
            return render_oauth_error("server_error", "")
        access_token = token_response.json().get("access_token")
        info = await client.get(USERINFO_URL, headers={"Authorization": f"Bearer {access_token}"})
    if info.status_code != 200:
        return render_oauth_error("server_error", "")
    session_id = secrets.token_urlsafe(32)
    sessions[session_id] = info.json()
    response = redirect("/")
    response.add_header(b"Set-Cookie", f"portal_session={session_id}; HttpOnly; Secure; SameSite=Lax; Path=/".encode())
    return response


@app.router.get("/logout")
async def logout(request: Request):
    sessions.pop(request.cookies.get("portal_session"), None)
    response = redirect("/")
    response.add_header(b"Set-Cookie", b"portal_session=; Max-Age=0; Path=/")
    return response


@app.router.get("/health")
async def health(request: Request):
    return Response(200, content=None)


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", "8000")))