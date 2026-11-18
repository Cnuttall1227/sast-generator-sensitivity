import os
import logging
from typing import Any

import uvicorn
import yaml
from fastapi import Depends, FastAPI, File, Header, HTTPException, UploadFile

API_KEYS = set(filter(None, os.environ.get("PIPELINE_LINT_KEYS", "").split(",")))
MAX_FILE_BYTES = 128 * 1024
KNOWN_STAGES = {"lint", "test", "build", "package", "deploy"}
KNOWN_RUNNERS = {"ubuntu-22.04", "ubuntu-24.04", "macos-14", "windows-2022"}

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("pipeline-lint")

app = FastAPI(title="Pipeline config linter")


def require_key(x_api_key: str = Header(default="")):
    if not API_KEYS or x_api_key not in API_KEYS:
        raise HTTPException(status_code=401, detail="API key required")


def parse_pipeline(raw: bytes) -> Any:
    return yaml.load(raw, Loader=yaml.Loader)


def lint_job(name, job, problems, warnings):
    if not isinstance(job, dict):
        problems.append(f"job '{name}' must be a mapping")
        return
    stage = job.get("stage")
    if stage not in KNOWN_STAGES:
        problems.append(f"job '{name}': stage must be one of {', '.join(sorted(KNOWN_STAGES))}")
    runner = job.get("runs-on")
    if runner not in KNOWN_RUNNERS:
        problems.append(f"job '{name}': runs-on must be one of {', '.join(sorted(KNOWN_RUNNERS))}")
    steps = job.get("steps")
    if not isinstance(steps, list) or not steps:
        problems.append(f"job '{name}' needs a non-empty steps list")
        return
    for index, step in enumerate(steps, start=1):
        if not isinstance(step, dict) or not ({"run", "uses"} & step.keys()):
            problems.append(f"job '{name}' step {index}: needs 'run' or 'uses'")
        elif "uses" in step and "@" not in str(step["uses"]):
            warnings.append(f"job '{name}' step {index}: pin '{step['uses']}' to a version")
    timeout = job.get("timeout-minutes")
    if timeout is None:
        warnings.append(f"job '{name}': set timeout-minutes so stuck runs don't burn minutes")
    elif not isinstance(timeout, int) or not 1 <= timeout <= 360:
        problems.append(f"job '{name}': timeout-minutes must be 1-360")


def lint_pipeline(config):
    problems, warnings = [], []
    if not isinstance(config, dict):
        return ["the file must contain a mapping at the top level"], []
    if "name" not in config:
        warnings.append("give the pipeline a name")
    jobs = config.get("jobs")
    if not isinstance(jobs, dict) or not jobs:
        problems.append("the pipeline needs at least one job under 'jobs'")
        return problems, warnings
    for name, job in jobs.items():
        lint_job(str(name), job, problems, warnings)
    needs_graph = {n: j.get("needs", []) for n, j in jobs.items() if isinstance(j, dict)}
    for name, needs in needs_graph.items():
        for dependency in needs if isinstance(needs, list) else [needs]:
            if dependency not in jobs:
                problems.append(f"job '{name}' needs unknown job '{dependency}'")
    return problems, warnings


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/lint", dependencies=[Depends(require_key)])
async def lint(file: UploadFile = File(...)):
    raw = await file.read(MAX_FILE_BYTES + 1)
    if len(raw) > MAX_FILE_BYTES:
        raise HTTPException(status_code=413, detail="file too large")
    try:
        config = parse_pipeline(raw)
    except yaml.YAMLError as exc:
        mark = getattr(exc, "problem_mark", None)
        where = f" at line {mark.line + 1}" if mark else ""
        return {"valid": False, "problems": [f"YAML syntax error{where}"], "warnings": []}
    problems, warnings = lint_pipeline(config)
    log.info("Linted %s: %d problem(s), %d warning(s)", file.filename, len(problems), len(warnings))
    return {"valid": not problems, "problems": problems, "warnings": warnings}


if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=int(os.environ.get("PORT", "8000")))