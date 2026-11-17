import json
import subprocess
from datetime import datetime, timezone
from urllib.parse import parse_qs

from sanic import Sanic
from sanic.response import json as json_response


app = Sanic("CommunityCinemaSubtitleDesk")

FILMS = {
    "river": {
        "title": "Along the River",
        "duration_minutes": 82,
        "language": "English",
    },
    "market": {
        "title": "Market Day",
        "duration_minutes": 74,
        "language": "Spanish",
    },
    "mountain": {
        "title": "Mountain Letters",
        "duration_minutes": 91,
        "language": "French",
    },
}


def current_time():
    return datetime.now(timezone.utc).isoformat()


def inspect_dictionary(language):
    import re

    if not isinstance(language, str) or not language.strip():
        return {"ok": False, "error": "Dictionary language is required."}

    language = language.strip()

    if len(language) > 100:
        return {"ok": False, "error": "Dictionary language is too long."}

    if not re.fullmatch(r"[A-Za-z]{2,3}(?:[_-][A-Za-z0-9]+)*", language):
        return {"ok": False, "error": "Invalid dictionary language."}

    try:
        result = subprocess.run(
            ["aspell", f"--lang={language}", "dump", "master"],
            shell=False,
            capture_output=True,
            text=True,
            timeout=5,
        )
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": "Dictionary inspection timed out."}
    except OSError:
        return {"ok": False, "error": "Dictionary inspection could not start."}

    return {
        "ok": result.returncode == 0,
        "language": language,
        "dictionary_sample": result.stdout[:3000],
        "errors": result.stderr[:1000],
        "checked_at": current_time(),
    }


@app.before_server_start
async def initialize_application(application, loop):
    application.ctx.screenings = []


@app.get("/")
async def index(request):
    return json_response(
        {
            "application": "Community Cinema Subtitle Desk",
            "films": "/films",
            "screenings": "/screenings",
            "dictionary_check": "/subtitles/dictionary",
            "selector": "language field in subtitle_preferences cookie",
        }
    )


@app.get("/films")
async def list_films(request):
    return json_response(
        {
            "films": [
                {"id": film_id, **details}
                for film_id, details in FILMS.items()
            ]
        }
    )


@app.get("/screenings")
async def list_screenings(request):
    return json_response({"screenings": request.app.ctx.screenings})


@app.post("/screenings")
async def create_screening(request):
    try:
        payload = json.loads(request.body)
    except (ValueError, UnicodeError):
        return json_response({"error": "Invalid JSON."}, status=400)

    if not isinstance(payload, dict):
        return json_response({"error": "Expected an object."}, status=400)

    film_id = payload.get("film_id")
    organizer = payload.get("organizer")

    if not isinstance(film_id, str) or film_id not in FILMS:
        return json_response({"error": "Unknown film."}, status=400)

    if not isinstance(organizer, str) or not organizer.strip():
        return json_response({"error": "Organizer is required."}, status=400)

    screenings = request.app.ctx.screenings
    screening = {
        "id": len(screenings) + 1,
        "film_id": film_id,
        "organizer": organizer,
        "created_at": current_time(),
    }
    screenings.append(screening)
    return json_response(screening, status=201)


@app.get("/subtitles/dictionary")
async def check_dictionary(request):
    import asyncio

    cookie = request.cookies.get(
        "subtitle_preferences",
        "language=en",
    )
    preferences = parse_qs(cookie)
    language = preferences.get("language", ["en"])[0]
    result = await asyncio.to_thread(inspect_dictionary, language)
    return json_response(result)


if __name__ == "__main__":
    app.run(
        host="127.0.0.1",
        port=8360,
        debug=False,
        single_process=True,
    )
