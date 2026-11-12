import os
import sys
import json
import uuid
import logging
from datetime import datetime, timezone

from django.conf import settings

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DROP_ROOT = os.environ.get("DROPBOX_ROOT", "/srv/dropbox")
MAX_UPLOAD_BYTES = 20 * 1024 * 1024
ALLOWED_EXTENSIONS = {".pdf", ".png", ".jpg", ".txt", ".csv", ".docx"}

settings.configure(
    DEBUG=False,
    SECRET_KEY=os.environ.get("DJANGO_SECRET_KEY", "replace-this-in-production"),
    ALLOWED_HOSTS=os.environ.get("ALLOWED_HOSTS", "localhost").split(","),
    ROOT_URLCONF=__name__,
    MIDDLEWARE=[
        "django.middleware.security.SecurityMiddleware",
        "django.middleware.common.CommonMiddleware",
    ],
    DATA_UPLOAD_MAX_MEMORY_SIZE=MAX_UPLOAD_BYTES,
    FILE_UPLOAD_MAX_MEMORY_SIZE=MAX_UPLOAD_BYTES,
)

import django  # noqa: E402
from django.core.wsgi import get_wsgi_application  # noqa: E402
from django.http import HttpResponseBadRequest, HttpResponseNotAllowed, JsonResponse  # noqa: E402
from django.urls import path  # noqa: E402
from django.views.decorators.csrf import csrf_exempt  # noqa: E402

django.setup()

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("dropbox")

API_TOKEN = os.environ.get("DROPBOX_TOKEN", "change-me")


def authorized(request):
    return request.headers.get("Authorization", "") == f"Bearer {API_TOKEN}"


def store_submission(project, upload):
    extension = os.path.splitext(upload.name)[1].lower()
    if extension not in ALLOWED_EXTENSIONS:
        raise ValueError(f"file type {extension or '(none)'} is not accepted")
    project_dir = os.path.join(DROP_ROOT, project)
    os.makedirs(project_dir, exist_ok=True)
    stored_name = f"{datetime.now(timezone.utc):%Y%m%dT%H%M%S}-{uuid.uuid4().hex[:8]}{extension}"
    destination = os.path.join(project_dir, stored_name)
    with open(destination, "wb") as handle:
        for chunk in upload.chunks():
            handle.write(chunk)
    meta_path = destination + ".json"
    with open(meta_path, "w", encoding="utf-8") as handle:
        json.dump({
            "original_name": os.path.basename(upload.name),
            "size": upload.size,
            "content_type": upload.content_type,
            "stored_at": datetime.now(timezone.utc).isoformat(),
        }, handle, indent=2)
    return stored_name


def project_listing(project_dir):
    entries = []
    for name in sorted(os.listdir(project_dir)):
        if not name.endswith(".json"):
            continue
        with open(os.path.join(project_dir, name), "r", encoding="utf-8") as handle:
            meta = json.load(handle)
        entries.append({"file": name[:-5], **meta})
    return entries


@csrf_exempt
def submit(request):
    if request.method != "POST":
        return HttpResponseNotAllowed(["POST"])
    if not authorized(request):
        return JsonResponse({"error": "unauthorized"}, status=401)
    project = request.POST.get("project", "").strip()
    upload = request.FILES.get("file")
    if not project or upload is None:
        return HttpResponseBadRequest("project and file are required")
    if upload.size > MAX_UPLOAD_BYTES:
        return JsonResponse({"error": "file too large"}, status=413)
    try:
        stored = store_submission(project, upload)
    except ValueError as exc:
        return JsonResponse({"error": str(exc)}, status=400)
    log.info("Stored %s for project %s", stored, project)
    return JsonResponse({"project": project, "file": stored}, status=201)


def list_project(request, project):
    if not authorized(request):
        return JsonResponse({"error": "unauthorized"}, status=401)
    if not project.isalnum():
        return HttpResponseBadRequest("invalid project name")
    project_dir = os.path.join(DROP_ROOT, project)
    if not os.path.isdir(project_dir):
        return JsonResponse({"error": "no such project"}, status=404)
    return JsonResponse({"project": project, "files": project_listing(project_dir)})


def health(request):
    return JsonResponse({"status": "ok"})


urlpatterns = [
    path("health", health),
    path("submissions", submit),
    path("projects/<str:project>", list_project),
]

application = get_wsgi_application()

if __name__ == "__main__":
    from django.core.management import execute_from_command_line

    execute_from_command_line([sys.argv[0], "runserver", os.environ.get("BIND", "0.0.0.0:8000"), "--noreload"])