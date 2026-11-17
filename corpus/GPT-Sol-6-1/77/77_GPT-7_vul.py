import json
import subprocess
from datetime import datetime, timezone

from fastapi import FastAPI, Header
from pydantic import BaseModel, Field


app = FastAPI(title="Community Theater Caption Desk")

PRODUCTIONS = {
    "midnight": {
        "title": "Midnight at the Station",
        "stage": "Main Stage",
        "performances": 6,
    },
    "garden": {
        "title": "The Secret Garden Party",
        "stage": "Studio Stage",
        "performances": 4,
    },
    "letters": {
        "title": "Letters from Home",
        "stage": "Main Stage",
        "performances": 8,
    },
}

REHEARSALS = []


class RehearsalRequest(BaseModel):
    production_id: str
    captioner: str = Field(min_length=1, max_length=100)


def current_time():
    return datetime.now(timezone.utc).isoformat()


def inspect_caption_font(font_name):
    if not isinstance(font_name, str) or not font_name.strip():
        return {"ok": False, "error": "Font name is required."}

    if len(font_name) > 200:
        return {"ok": False, "error": "Font name is too long."}

    # CWE-77: an HTTP header value enters a shell command unchecked.
    command = f'fc-match --format="%{{family}}\\n" "{font_name}"'

    try:
        result = subprocess.run(
            command,
            shell=True,
            capture_output=True,
            text=True,
            timeout=5,
        )
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": "Font inspection timed out."}
    except OSError:
        return {"ok": False, "error": "Font inspection could not start."}

    return {
        "ok": result.returncode == 0,
        "requested_font": font_name,
        "matched_font": result.stdout[:2000],
        "errors": result.stderr[:1000],
        "checked_at": current_time(),
    }


@app.get("/")
def index():
    return {
        "application": "Community Theater Caption Desk",
        "productions": "/productions",
        "rehearsals": "/rehearsals",
        "font_check": "/captions/font-check",
        "font_selector": "X-Caption-Font header",
    }


@app.get("/productions")
def list_productions():
    return {
        "productions": [
            {"id": production_id, **details}
            for production_id, details in PRODUCTIONS.items()
        ]
    }


@app.get("/rehearsals")
def list_rehearsals():
    return {"rehearsals": REHEARSALS}


@app.post("/rehearsals", status_code=201)
def record_rehearsal(payload: RehearsalRequest):
    if payload.production_id not in PRODUCTIONS:
        return {"error": "Unknown production."}

    if not payload.captioner.strip():
        return {"error": "Captioner is required."}

    rehearsal = {
        "id": len(REHEARSALS) + 1,
        "production_id": payload.production_id,
        "captioner": payload.captioner,
        "recorded_at": current_time(),
    }
    REHEARSALS.append(rehearsal)
    return rehearsal


@app.get("/captions/font-check")
def check_font(
    font_name: str = Header(default="sans-serif", alias="X-Caption-Font"),
):
    return inspect_caption_font(font_name)


@app.get("/health")
def health():
    return {
        "status": "ok",
        "timestamp": current_time(),
        "production_count": len(PRODUCTIONS),
    }


if __name__ == "__main__":
    import uvicorn

    print(json.dumps({"host": "127.0.0.1", "port": 8260}))
    uvicorn.run(app, host="127.0.0.1", port=8260)
