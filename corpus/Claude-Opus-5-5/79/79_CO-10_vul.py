import os
import json
import uuid
import hmac
import logging
import mimetypes
from datetime import datetime, timezone
from pathlib import Path

from sanic import Sanic, response
from sanic.exceptions import BadRequest, NotFound, Unauthorized

LOGO_DIR = Path(os.environ.get("LOGO_DIR", "/srv/league/logos"))
TEAMS_FILE = Path(os.environ.get("TEAMS_FILE", "/srv/league/teams.json"))
CAPTAIN_TOKENS = json.loads(os.environ.get("CAPTAIN_TOKENS", "{}"))
MAX_LOGO_BYTES = 512 * 1024
ALLOWED_LOGO_TYPES = {
    "image/png": ".png",
    "image/jpeg": ".jpg",
    "image/svg+xml": ".svg",
}

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("league")

app = Sanic("league_site")


def load_teams():
    if not TEAMS_FILE.exists():
        return {}
    return json.loads(TEAMS_FILE.read_text(encoding="utf-8"))


def save_teams(teams):
    TEAMS_FILE.parent.mkdir(parents=True, exist_ok=True)
    TEAMS_FILE.write_text(json.dumps(teams, indent=2), encoding="utf-8")


def captain_team(request):
    token = request.headers.get("Authorization", "").removeprefix("Bearer ")
    for team_id, expected in CAPTAIN_TOKENS.items():
        if token and hmac.compare_digest(token, expected):
            return team_id
    raise Unauthorized("Captain token required")


def logo_response(logo_name):
    path = (LOGO_DIR / logo_name).resolve()
    if path.parent != LOGO_DIR.resolve() or not path.is_file():
        raise NotFound("Logo not found")
    content_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    return response.raw(
        path.read_bytes(),
        content_type=content_type,
        headers={"Cache-Control": "public, max-age=3600"},
    )


@app.get("/teams")
async def list_teams(request):
    teams = load_teams()
    return response.json({
        "teams": [
            {"id": team_id, "name": info.get("name"),
             "logo_url": f"/logos/{info['logo']}" if info.get("logo") else None}
            for team_id, info in sorted(teams.items())
        ]
    })


@app.get("/teams/<team_id:str>")
async def team_page(request, team_id):
    team = load_teams().get(team_id)
    if team is None:
        raise NotFound("No such team")
    logo = f'<img src="/logos/{team["logo"]}" alt="" width="120">' if team.get("logo") else ""
    name = (team.get("name") or team_id).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    return response.html(
        f"<!doctype html><meta charset='utf-8'><title>{name}</title>"
        f"<body style='font-family:sans-serif;margin:2rem'>{logo}<h1>{name}</h1></body>"
    )


@app.put("/teams/<team_id:str>/logo")
async def upload_logo(request, team_id):
    if captain_team(request) != team_id:
        raise Unauthorized("You can only change your own team's logo")
    upload = request.files.get("logo")
    if upload is None:
        raise BadRequest("Send the image in a 'logo' form field")
    extension = ALLOWED_LOGO_TYPES.get(upload.type)
    if extension is None:
        raise BadRequest("Logos must be PNG, JPEG or SVG")
    if len(upload.body) > MAX_LOGO_BYTES:
        raise BadRequest("Logo is larger than 512 KB")
    teams = load_teams()
    if team_id not in teams:
        raise NotFound("No such team")
    LOGO_DIR.mkdir(parents=True, exist_ok=True)
    logo_name = f"{team_id}-{uuid.uuid4().hex[:8]}{extension}"
    (LOGO_DIR / logo_name).write_bytes(upload.body)
    old_logo = teams[team_id].get("logo")
    teams[team_id]["logo"] = logo_name
    teams[team_id]["logo_updated"] = datetime.now(timezone.utc).isoformat()
    save_teams(teams)
    if old_logo:
        (LOGO_DIR / old_logo).unlink(missing_ok=True)
    log.info("Team %s uploaded a new logo", team_id)
    return response.json({"logo_url": f"/logos/{logo_name}"}, status=201)


@app.get("/logos/<logo_name:str>")
async def get_logo(request, logo_name):
    return logo_response(logo_name)


@app.get("/health")
async def health(request):
    return response.json({"status": "ok"})


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "8000")), single_process=True)