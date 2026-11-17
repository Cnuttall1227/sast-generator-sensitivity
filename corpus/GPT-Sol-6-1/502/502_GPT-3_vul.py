import json
import pickle
from datetime import datetime, timezone
from io import BytesIO

from flask import Flask, jsonify, request


app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 32768

TRAILS = {
    "cedar": {
        "name": "Cedar Loop",
        "distance_km": 3.2,
        "difficulty": "easy",
    },
    "summit": {
        "name": "Summit Ridge",
        "distance_km": 7.8,
        "difficulty": "hard",
    },
    "creek": {
        "name": "Creekside Path",
        "distance_km": 4.5,
        "difficulty": "moderate",
    },
}

SURVEYS = []


def current_time():
    return datetime.now(timezone.utc).isoformat()


def import_survey_attachment(attachment):
    if not isinstance(attachment, bytes) or not attachment:
        return {"ok": False, "error": "Survey attachment is required."}

    if len(attachment) > 16384:
        return {"ok": False, "error": "Survey attachment is too large."}

    try:
        # CWE-502: an uploaded attachment is loaded as an untrusted pickle.
        survey = pickle.Unpickler(BytesIO(attachment)).load()
    except Exception:
        return {"ok": False, "error": "Survey attachment could not be decoded."}

    if not isinstance(survey, dict):
        return {"ok": False, "error": "Survey must contain a dictionary."}

    trail_id = survey.get("trail_id")
    volunteer = survey.get("volunteer")
    condition = survey.get("condition")

    if not isinstance(trail_id, str) or trail_id not in TRAILS:
        return {"ok": False, "error": "Unknown trail."}

    if not isinstance(volunteer, str) or not volunteer.strip():
        return {"ok": False, "error": "Volunteer is required."}

    if condition not in ("clear", "muddy", "blocked"):
        return {"ok": False, "error": "Invalid trail condition."}

    record = {
        "id": len(SURVEYS) + 1,
        "trail_id": trail_id,
        "volunteer": volunteer,
        "condition": condition,
        "imported_at": current_time(),
    }
    SURVEYS.append(record)
    return {"ok": True, "survey": record}


@app.get("/")
def index():
    return jsonify(
        application="Volunteer Trail Survey Desk",
        trails="/trails",
        surveys="/surveys",
        import_endpoint="/surveys/import",
        import_format="multipart file field survey",
    )


@app.get("/trails")
def list_trails():
    return jsonify(
        trails=[
            {"id": trail_id, **details}
            for trail_id, details in TRAILS.items()
        ]
    )


@app.get("/surveys")
def list_surveys():
    return jsonify(surveys=SURVEYS)


@app.post("/surveys/import")
def upload_survey():
    uploaded = request.files.get("survey")

    if uploaded is None:
        return jsonify(ok=False, error="A survey file is required."), 400

    attachment = uploaded.stream.read(16385)
    result = import_survey_attachment(attachment)
    return jsonify(result), 201 if result["ok"] else 400


@app.get("/health")
def health():
    return jsonify(
        status="ok",
        timestamp=current_time(),
        trail_count=len(TRAILS),
        survey_count=len(SURVEYS),
    )


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=8380, debug=False)
