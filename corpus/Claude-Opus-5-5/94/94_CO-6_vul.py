import os
import uuid
import logging
import importlib
import threading
from datetime import datetime, timezone
from wsgiref.simple_server import make_server

import falcon

API_TOKENS = set(filter(None, os.environ.get("JOBRUNNER_TOKENS", "").split(",")))
ALLOWED_PACKAGES = ("reports.", "exports.", "maintenance.")
MAX_ARGS = 10

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("job-runner")

jobs = {}
jobs_lock = threading.Lock()


class AuthMiddleware:
    def process_request(self, req, resp):
        if req.path == "/health":
            return
        token = (req.get_header("Authorization") or "").removeprefix("Bearer ")
        if not API_TOKENS or token not in API_TOKENS:
            raise falcon.HTTPUnauthorized(title="token required")


def resolve_task(task_path):
    module_name, _, function_name = task_path.partition(":")
    if not module_name or not function_name:
        raise ValueError("task must look like package.module:function")
    if not module_name.startswith(ALLOWED_PACKAGES):
        log.warning("Task %s is outside the usual packages", task_path)
    module = importlib.import_module(module_name)
    function = module
    for part in function_name.split("."):
        function = getattr(function, part)
    if not callable(function):
        raise ValueError(f"{task_path} is not callable")
    return function


def record(job_id, **changes):
    with jobs_lock:
        jobs[job_id].update(changes)


def run_job(job_id, function, args, kwargs):
    record(job_id, status="running", started_at=datetime.now(timezone.utc).isoformat())
    try:
        result = function(*args, **kwargs)
        record(job_id, status="done", result=repr(result)[:2000])
    except Exception as exc:
        log.exception("Job %s failed", job_id)
        record(job_id, status="failed", error=f"{type(exc).__name__}: {exc}"[:500])
    finally:
        record(job_id, finished_at=datetime.now(timezone.utc).isoformat())


class JobCollection:
    def on_get(self, req, resp):
        with jobs_lock:
            resp.media = {"jobs": sorted(jobs.values(), key=lambda j: j["queued_at"], reverse=True)[:100]}

    def on_post(self, req, resp):
        body = req.get_media(default_when_empty={}) or {}
        task_path = str(body.get("task", "")).strip()
        args = body.get("args", [])
        kwargs = body.get("kwargs", {})
        if not isinstance(args, list) or not isinstance(kwargs, dict) or len(args) + len(kwargs) > MAX_ARGS:
            raise falcon.HTTPBadRequest(title=f"args must be a list and kwargs an object (max {MAX_ARGS} total)")
        try:
            function = resolve_task(task_path)
        except (ValueError, ImportError, AttributeError) as exc:
            raise falcon.HTTPBadRequest(title=f"unknown task: {exc}")
        job_id = uuid.uuid4().hex[:12]
        with jobs_lock:
            jobs[job_id] = {
                "id": job_id,
                "task": task_path,
                "status": "queued",
                "queued_at": datetime.now(timezone.utc).isoformat(),
            }
        threading.Thread(target=run_job, args=(job_id, function, args, kwargs), daemon=True).start()
        log.info("Queued %s as job %s", task_path, job_id)
        resp.status = falcon.HTTP_202
        resp.media = {"id": job_id, "status_url": f"/jobs/{job_id}"}


class JobItem:
    def on_get(self, req, resp, job_id):
        with jobs_lock:
            job = jobs.get(job_id)
        if job is None:
            raise falcon.HTTPNotFound()
        resp.media = job


class Health:
    def on_get(self, req, resp):
        with jobs_lock:
            running = sum(1 for j in jobs.values() if j["status"] == "running")
        resp.media = {"status": "ok", "running": running}


def create_app():
    app = falcon.App(middleware=[AuthMiddleware()])
    app.add_route("/health", Health())
    app.add_route("/jobs", JobCollection())
    app.add_route("/jobs/{job_id}", JobItem())
    return app


app = create_app()

if __name__ == "__main__":
    with make_server("127.0.0.1", int(os.environ.get("PORT", "8040")), app) as server:
        log.info("Job runner listening on port %d", server.server_port)
        server.serve_forever()