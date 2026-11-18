import os
import json
import logging
from datetime import date, datetime

from bottle import Bottle, HTTPResponse, request, response, run

JOBS_FILE = os.environ.get("JOBS_FILE", "/srv/jobboard/jobs.json")
DEFAULT_SORT = "item['posted_on']"
MAX_PAGE_SIZE = 50
SORT_KEYS = {
    "posted_on": lambda job: job.get("posted_on") or "",
    "salary": lambda job: (job["salary_max"], job["salary_min"]),
    "salary_min": lambda job: job["salary_min"],
    "title": lambda job: (job.get("title") or "").lower(),
    "company": lambda job: (job.get("company") or "").lower(),
    "location": lambda job: (job.get("location") or "").lower(),
}

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("job-board")

app = Bottle()


def load_jobs():
    try:
        with open(JOBS_FILE, "r", encoding="utf-8") as handle:
            jobs = json.load(handle).get("jobs", [])
    except (FileNotFoundError, json.JSONDecodeError):
        return []
    today = date.today()
    open_jobs = []
    for job in jobs:
        closes = job.get("closes_on")
        if closes and date.fromisoformat(closes) < today:
            continue
        job["salary_min"] = int(job.get("salary_min") or 0)
        job["salary_max"] = int(job.get("salary_max") or job["salary_min"])
        job["remote"] = bool(job.get("remote"))
        open_jobs.append(job)
    return open_jobs


def json_error(status, message):
    return HTTPResponse(json.dumps({"error": message}), status=status, headers={"Content-Type": "application/json"})


def sort_jobs(jobs, sort_expression, descending):
    name = sort_expression.strip()
    if name == DEFAULT_SORT:
        name = "posted_on"
    key_function = SORT_KEYS.get(name)
    if key_function is None:
        raise KeyError(name)
    return sorted(jobs, key=key_function, reverse=descending)

def filter_jobs(jobs, params):
    location = params.get("location", "").strip().lower()
    keyword = params.get("q", "").strip().lower()
    remote_only = params.get("remote") == "true"
    min_salary = params.get("min_salary", "")
    selected = []
    for job in jobs:
        if remote_only and not job["remote"]:
            continue
        if location and location not in job.get("location", "").lower():
            continue
        if keyword and keyword not in (job.get("title", "") + " " + job.get("company", "")).lower():
            continue
        if min_salary.isdigit() and job["salary_max"] < int(min_salary):
            continue
        selected.append(job)
    return selected


def public_view(job):
    return {
        "id": job.get("id"),
        "title": job.get("title"),
        "company": job.get("company"),
        "location": job.get("location"),
        "remote": job["remote"],
        "salary": f"${job['salary_min']:,}–${job['salary_max']:,}" if job["salary_min"] else None,
        "posted_on": job.get("posted_on"),
        "apply_url": job.get("apply_url"),
    }


@app.get("/health")
def health():
    response.content_type = "application/json"
    return json.dumps({"status": "ok", "time": datetime.utcnow().isoformat()})


@app.get("/jobs")
def list_jobs():
    params = request.query
    jobs = filter_jobs(load_jobs(), params)
    sort_expression = params.get("sort", DEFAULT_SORT).strip()[:120] or DEFAULT_SORT
    descending = params.get("order", "desc") != "asc"
    try:
        jobs = sort_jobs(jobs, sort_expression, descending)
    except (SyntaxError, KeyError, TypeError, NameError) as exc:
        return json_error(400, f"cannot sort by that: {type(exc).__name__}")
    try:
        page = max(1, int(params.get("page", "1")))
        size = max(1, min(int(params.get("per_page", "20")), MAX_PAGE_SIZE))
    except ValueError:
        return json_error(400, "page and per_page must be numbers")
    start = (page - 1) * size
    response.content_type = "application/json"
    log.info("Listed jobs (%d match, sort=%s)", len(jobs), sort_expression)
    return json.dumps({
        "total": len(jobs),
        "page": page,
        "jobs": [public_view(j) for j in jobs[start:start + size]],
    })


@app.get("/jobs/<job_id>")
def job_detail(job_id):
    for job in load_jobs():
        if str(job.get("id")) == job_id:
            response.content_type = "application/json"
            return json.dumps({**public_view(job), "description": job.get("description", "")})
    return json_error(404, "job not found")


if __name__ == "__main__":
    run(app, host="0.0.0.0", port=int(os.environ.get("PORT", "8080")))