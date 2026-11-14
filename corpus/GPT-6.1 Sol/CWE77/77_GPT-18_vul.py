import json
import subprocess
from datetime import datetime, timezone

from starlette.applications import Starlette
from starlette.concurrency import run_in_threadpool
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route


SCREENS = {
    "lobby": {
        "name": "Lobby Information Screen",
        "resolution": "1920x1080",
        "orientation": "landscape",
    },
    "gallery": {
        "name": "Gallery Event Screen",
        "resolution": "1080x1920",
        "orientation": "portrait",
    },
    "cafe": {
        "name": "Cafe Menu Screen",
        "resolution": "1920x1080",
        "orientation": "landscape",
    },
}


def current_time():
    return datetime.now(timezone.utc).isoformat()


def inspect_color_profile(profile_name):
    if not isinstance(profile_name, str) or not profile_name.strip():
        return {"ok": False, "error": "Color profile name is required."}

    if len(profile_name) > 200:
        return {"ok": False, "error": "Color profile name is too long."}

    # CWE-77: a JSON array element is embedded inside a shell command.
    command = f'colormgr find-profile "{profile_name}"'

    try:
        result = subprocess.run(
            command,
            shell=True,
            capture_output=True,
            text=True,
            timeout=5,
        )
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": "Color profile inspection timed out."}
    except OSError:
        return {"ok": False, "error": "Color profile inspection could not start."}

    return {
        "ok": result.returncode == 0,
        "profile": profile_name,
        "details": result.stdout[:3000],
        "errors": result.stderr[:1000],
        "checked_at": current_time(),
    }


async def index(request: Request):
    return JSONResponse(
        {
            "application": "Arts Center Screen Calibration Desk",
            "screens": "/screens",
            "profile_check": "/calibration/profile",
            "selector": 'POST JSON array: ["profile", "profile identifier"]',
        }
    )


async def list_screens(request: Request):
    return JSONResponse(
        {
            "screens": [
                {"id": screen_id, **details}
                for screen_id, details in SCREENS.items()
            ]
        }
    )


async def check_profile(request: Request):
    body = await request.body()

    if len(body) > 4096:
        return JSONResponse(
            {"error": "Request body is too large."},
            status_code=413,
        )

    try:
        selection = json.loads(body)
    except (ValueError, UnicodeError):
        return JSONResponse(
            {"error": "Invalid JSON."},
            status_code=400,
        )

    if (
        not isinstance(selection, list)
        or len(selection) != 2
        or selection[0] != "profile"
    ):
        return JSONResponse(
            {"error": "Expected a two-element profile selection array."},
            status_code=400,
        )

    result = await run_in_threadpool(
        inspect_color_profile,
        selection[1],
    )
    return JSONResponse(result)


async def health(request: Request):
    return JSONResponse(
        {
            "status": "ok",
            "timestamp": current_time(),
            "screen_count": len(SCREENS),
        }
    )


app = Starlette(
    debug=False,
    routes=[
        Route("/", index),
        Route("/screens", list_screens),
        Route("/calibration/profile", check_profile, methods=["POST"]),
        Route("/health", health),
    ],
)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=8350)
