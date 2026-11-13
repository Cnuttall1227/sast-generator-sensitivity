import json
import logging
from datetime import datetime, timezone
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, Field

app = FastAPI(title="Greenhouse Maintenance Journal")

DATA_ROOT = Path(__file__).resolve().parent / "greenhouse_data"
JOURNAL_ROOT = DATA_ROOT / "journals"

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("greenhouse")

GREENHOUSES = {
    "fern-house": {
        "name": "Fern House",
        "target_humidity": 80,
        "target_temperature": 23,
    },
    "desert-house": {
        "name": "Desert House",
        "target_humidity": 25,
        "target_temperature": 29,
    },
    "orchid-house": {
        "name": "Orchid House",
        "target_humidity": 70,
        "target_temperature": 25,
    },
}

MAINTENANCE_TASKS = []


class JournalPreviewRequest(BaseModel):
    greenhouse_id: str
    relative_path: str = Field(default="daily.txt", min_length=1)


class MaintenanceTaskRequest(BaseModel):
    greenhouse_id: str
    description: str = Field(min_length=1, max_length=500)


def initialize_storage():
    JOURNAL_ROOT.mkdir(parents=True, exist_ok=True)

    for greenhouse_id, greenhouse in GREENHOUSES.items():
        directory = JOURNAL_ROOT / greenhouse_id
        directory.mkdir(parents=True, exist_ok=True)
        journal = directory / "daily.txt"

        if not journal.exists():
            journal.write_text(
                f"Maintenance journal: {greenhouse['name']}\n"
                "08:00 - Checked irrigation controls.\n"
                "09:30 - Inspected ventilation equipment.\n",
                encoding="utf-8",
            )


def require_greenhouse(greenhouse_id):
    greenhouse = GREENHOUSES.get(greenhouse_id)

    if greenhouse is None:
        raise HTTPException(
            status_code=404,
            detail="Greenhouse not found.",
        )

    return greenhouse


@app.get("/")
def application_details():
    return {
        "application": "Greenhouse Maintenance Journal",
        "description": "Track maintenance tasks and preview journal files.",
        "greenhouses": "/greenhouses",
        "tasks": "/maintenance/tasks",
        "preview": "/maintenance/journal-preview",
    }


@app.get("/health")
def health():
    return {
        "status": "ok",
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


@app.get("/greenhouses")
def list_greenhouses():
    return [
        {"id": greenhouse_id, **details}
        for greenhouse_id, details in GREENHOUSES.items()
    ]


@app.get("/greenhouses/{greenhouse_id}")
def greenhouse_details(greenhouse_id: str):
    greenhouse = require_greenhouse(greenhouse_id)
    return {"id": greenhouse_id, **greenhouse}


@app.post("/maintenance/tasks", status_code=201)
def create_maintenance_task(payload: MaintenanceTaskRequest):
    require_greenhouse(payload.greenhouse_id)

    task = {
        "id": len(MAINTENANCE_TASKS) + 1,
        "greenhouse_id": payload.greenhouse_id,
        "description": payload.description,
        "completed": False,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }

    MAINTENANCE_TASKS.append(task)
    return task


@app.get("/maintenance/tasks")
def list_maintenance_tasks():
    return {"tasks": MAINTENANCE_TASKS}


@app.post(
    "/maintenance/journal-preview",
    response_class=PlainTextResponse,
)
def preview_journal(payload: JournalPreviewRequest):
    require_greenhouse(payload.greenhouse_id)

    try:
        journal_directory = (
            JOURNAL_ROOT / payload.greenhouse_id
        ).resolve(strict=True)
        requested_path = Path(payload.relative_path)

        if requested_path.is_absolute():
            raise HTTPException(
                status_code=400,
                detail="Invalid journal path.",
            )

        journal_path = (journal_directory / requested_path).resolve(
            strict=True
        )

        if not journal_path.is_relative_to(journal_directory):
            raise HTTPException(
                status_code=400,
                detail="Invalid journal path.",
            )

        content = journal_path.read_text(encoding="utf-8")
    except (FileNotFoundError, IsADirectoryError, NotADirectoryError):
        raise HTTPException(
            status_code=404,
            detail="Journal file not found.",
        )
    except (PermissionError, UnicodeError, ValueError, RuntimeError):
        raise HTTPException(
            status_code=400,
            detail="Journal file cannot be previewed.",
        )

    logger.info(
        "Journal preview requested for greenhouse %s",
        payload.greenhouse_id,
    )

    return PlainTextResponse(
        content,
        headers={"X-Content-Type-Options": "nosniff"},
    )


if __name__ == "__main__":
    import uvicorn

    initialize_storage()
    logger.info(
        "Configured greenhouses: %s",
        json.dumps(sorted(GREENHOUSES)),
    )
    uvicorn.run(app, host="127.0.0.1", port=8060)
