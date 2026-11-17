import json
import pickle
from datetime import datetime, timezone

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse


app = FastAPI(title="Community Observatory Exposure Desk")

TELESCOPES = {
    "reflector": {
        "name": "Main Reflector",
        "aperture_mm": 300,
        "location": "North Dome",
    },
    "refractor": {
        "name": "Wide-Field Refractor",
        "aperture_mm": 100,
        "location": "Roof Platform",
    },
    "solar": {
        "name": "Solar Telescope",
        "aperture_mm": 80,
        "location": "South Platform",
    },
}

EXPOSURES = []


def current_time():
    return datetime.now(timezone.utc).isoformat()


def import_exposure_sequence(serialized_sequence):
    if not isinstance(serialized_sequence, bytes) or not serialized_sequence:
        return {"ok": False, "error": "Exposure sequence is required."}

    if len(serialized_sequence) > 16384:
        return {"ok": False, "error": "Exposure sequence is too large."}

    try:
        # CWE-502: a PATCH request body is loaded as untrusted pickle.
        sequence = pickle.loads(serialized_sequence)
    except Exception:
        return {"ok": False, "error": "Exposure sequence could not be decoded."}

    if not isinstance(sequence, dict):
        return {"ok": False, "error": "Sequence must contain a dictionary."}

    telescope_id = sequence.get("telescope_id")
    observer = sequence.get("observer")
    seconds = sequence.get("seconds")

    if not isinstance(telescope_id, str) or telescope_id not in TELESCOPES:
        return {"ok": False, "error": "Unknown telescope."}

    if not isinstance(observer, str) or not observer.strip():
        return {"ok": False, "error": "Observer is required."}

    if type(seconds) is not int or not 1 <= seconds <= 600:
        return {"ok": False, "error": "Exposure must be 1–600 seconds."}

    return {
        "ok": True,
        "sequence": {
            "telescope_id": telescope_id,
            "observer": observer,
            "seconds": seconds,
            "imported_at": current_time(),
        },
    }


@app.get("/")
def index():
    return {
        "application": "Community Observatory Exposure Desk",
        "telescopes": "/telescopes",
        "exposures": "/exposures",
        "sequence_import": "/exposures/sequence",
        "import_format": "PATCH binary serialized exposure sequence",
    }


@app.get("/telescopes")
def list_telescopes():
    return {
        "telescopes": [
            {"id": telescope_id, **details}
            for telescope_id, details in TELESCOPES.items()
        ]
    }


@app.get("/exposures")
def list_exposures():
    return {"exposures": EXPOSURES}


@app.post("/exposures")
async def record_exposure(request: Request):
    try:
        payload = json.loads(await request.body())
    except (ValueError, UnicodeError):
        return JSONResponse({"error": "Invalid JSON."}, status_code=400)

    if not isinstance(payload, dict):
        return JSONResponse({"error": "Expected an object."}, status_code=400)

    telescope_id = payload.get("telescope_id")
    observer = payload.get("observer")

    if not isinstance(telescope_id, str) or telescope_id not in TELESCOPES:
        return JSONResponse({"error": "Unknown telescope."}, status_code=400)

    if not isinstance(observer, str) or not observer.strip():
        return JSONResponse({"error": "Observer is required."}, status_code=400)

    exposure = {
        "id": len(EXPOSURES) + 1,
        "telescope_id": telescope_id,
        "observer": observer,
        "recorded_at": current_time(),
    }
    EXPOSURES.append(exposure)
    return JSONResponse(exposure, status_code=201)


@app.patch("/exposures/sequence")
async def upload_sequence(request: Request):
    data = bytearray()

    async for chunk in request.stream():
        data.extend(chunk)
        if len(data) > 16384:
            return JSONResponse(
                {"ok": False, "error": "Exposure sequence is too large."},
                status_code=413,
            )

    result = import_exposure_sequence(bytes(data))
    return JSONResponse(result, status_code=200 if result["ok"] else 400)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=8460)
