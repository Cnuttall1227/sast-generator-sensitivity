import os
import base64
import hashlib
import mimetypes
from datetime import datetime, timezone
from typing import List, Optional

import strawberry
import uvicorn
from strawberry.asgi import GraphQL
from strawberry.types import Info

NOTEBOOK_ROOT = os.environ.get("NOTEBOOK_ROOT", "/srv/lab-notebook")
API_TOKENS = set(filter(None, os.environ.get("NOTEBOOK_TOKENS", "").split(",")))
MAX_ATTACHMENT_BYTES = 5 * 1024 * 1024


def require_token(info: Info) -> None:
    header = info.context["request"].headers.get("authorization", "")
    if header.removeprefix("Bearer ") not in API_TOKENS:
        raise PermissionError("Missing or invalid token")


def experiment_dir(experiment: str) -> str:
    if not experiment.isalnum():
        raise ValueError("Experiment ids are alphanumeric")
    path = os.path.join(NOTEBOOK_ROOT, experiment)
    if not os.path.isdir(path):
        raise LookupError(f"No experiment {experiment}")
    return path


def read_attachment(experiment: str, name: str) -> tuple:
    if not name or name in (".", "..") or "/" in name or "\\" in name or "\x00" in name:
        raise LookupError(f"No attachment {name}")
    folder = os.path.realpath(os.path.join(experiment_dir(experiment), "attachments"))
    path = os.path.realpath(os.path.join(folder, name))
    if os.path.dirname(path) != folder:
        raise LookupError(f"No attachment {name}")
    if not os.path.isfile(path):
        raise LookupError(f"No attachment {name}")
    if os.path.getsize(path) > MAX_ATTACHMENT_BYTES:
        raise ValueError("Attachment too large to return inline")
    with open(path, "rb") as handle:
        data = handle.read()
    return path, data


@strawberry.type
class AttachmentInfo:
    name: str
    size: int
    modified: str


@strawberry.type
class Attachment:
    name: str
    content_type: str
    size: int
    sha256: str
    content_base64: str


@strawberry.type
class Experiment:
    id: str
    title: str
    attachments: List[AttachmentInfo]


def experiment_title(path: str, fallback: str) -> str:
    readme = os.path.join(path, "README.md")
    if os.path.isfile(readme):
        with open(readme, "r", encoding="utf-8", errors="replace") as handle:
            first = handle.readline().strip().lstrip("# ")
            if first:
                return first
    return fallback


def list_attachments(path: str) -> List[AttachmentInfo]:
    folder = os.path.join(path, "attachments")
    if not os.path.isdir(folder):
        return []
    items = []
    for name in sorted(os.listdir(folder)):
        full = os.path.join(folder, name)
        if os.path.isfile(full):
            stamp = datetime.fromtimestamp(os.path.getmtime(full), timezone.utc).isoformat()
            items.append(AttachmentInfo(name=name, size=os.path.getsize(full), modified=stamp))
    return items


@strawberry.type
class Query:
    @strawberry.field
    def experiments(self, info: Info) -> List[Experiment]:
        require_token(info)
        results = []
        for entry in sorted(os.listdir(NOTEBOOK_ROOT)):
            path = os.path.join(NOTEBOOK_ROOT, entry)
            if entry.isalnum() and os.path.isdir(path):
                results.append(Experiment(id=entry, title=experiment_title(path, entry),
                                          attachments=list_attachments(path)))
        return results

    @strawberry.field
    def experiment(self, info: Info, id: str) -> Optional[Experiment]:
        require_token(info)
        try:
            path = experiment_dir(id)
        except (ValueError, LookupError):
            return None
        return Experiment(id=id, title=experiment_title(path, id), attachments=list_attachments(path))

    @strawberry.field
    def attachment(self, info: Info, experiment: str, name: str) -> Attachment:
        require_token(info)
        path, data = read_attachment(experiment, name)
        return Attachment(
            name=os.path.basename(path),
            content_type=mimetypes.guess_type(path)[0] or "application/octet-stream",
            size=len(data),
            sha256=hashlib.sha256(data).hexdigest(),
            content_base64=base64.b64encode(data).decode("ascii"),
        )


schema = strawberry.Schema(query=Query)
app = GraphQL(schema, graphql_ide=None)

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", "8000")))