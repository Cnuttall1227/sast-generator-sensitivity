import os
import re
import timeit
import logging
import statistics

import uvicorn
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

MAX_PATTERN_LENGTH = 300
MAX_SAMPLE_LENGTH = 2000
REPEATS = 5
NUMBER = 200
SLOW_THRESHOLD_MS = 2.0

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("regex-bench")

FLAG_MAP = {"i": re.IGNORECASE, "m": re.MULTILINE, "s": re.DOTALL, "x": re.VERBOSE}


def parse_flags(flags):
    value = 0
    for letter in flags:
        if letter not in FLAG_MAP:
            raise ValueError(f"unknown flag {letter!r}; use any of {''.join(FLAG_MAP)}")
        value |= FLAG_MAP[letter]
    return value


def benchmark_pattern(pattern, sample, flags):
    compiled = re.compile(pattern, flags)
    setup = f"import re\ncompiled = re.compile({pattern!r}, {flags})\nsample = '{sample}'"
    timer = timeit.Timer("compiled.search(sample)", setup=setup)
    runs = timer.repeat(repeat=REPEATS, number=NUMBER)
    per_call_ms = [r / NUMBER * 1000 for r in runs]
    match = compiled.search(sample)
    return {
        "matched": match is not None,
        "match": match.group(0)[:200] if match else None,
        "groups": [g[:200] if g else g for g in match.groups()] if match else [],
        "median_ms": round(statistics.median(per_call_ms), 4),
        "best_ms": round(min(per_call_ms), 4),
        "worst_ms": round(max(per_call_ms), 4),
    }


def advice(result, pattern):
    notes = []
    if result["median_ms"] > SLOW_THRESHOLD_MS:
        notes.append("This pattern is slow on the sample; check for nested quantifiers like (a+)+.")
    if pattern.startswith(".*"):
        notes.append("A leading .* is usually unnecessary with search().")
    if re.search(r"\((?!\?)", pattern) and not result["groups"]:
        notes.append("Use (?:...) for groups you don't need to capture.")
    return notes


async def bench(request: Request):
    try:
        body = await request.json()
    except ValueError:
        return JSONResponse({"error": "invalid JSON"}, status_code=400)
    pattern = str(body.get("pattern", ""))
    sample = str(body.get("sample", ""))
    flags_text = str(body.get("flags", ""))
    if not pattern or len(pattern) > MAX_PATTERN_LENGTH:
        return JSONResponse({"error": f"pattern must be 1-{MAX_PATTERN_LENGTH} characters"}, status_code=400)
    if len(sample) > MAX_SAMPLE_LENGTH:
        return JSONResponse({"error": f"sample must be at most {MAX_SAMPLE_LENGTH} characters"}, status_code=400)
    try:
        flags = parse_flags(flags_text)
        result = benchmark_pattern(pattern, sample, flags)
    except re.error as exc:
        return JSONResponse({"error": f"invalid pattern: {exc}"}, status_code=400)
    except (ValueError, SyntaxError) as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)
    log.info("Benchmarked pattern of length %d: %.4f ms median", len(pattern), result["median_ms"])
    return JSONResponse({**result, "advice": advice(result, pattern)})


async def health(request: Request):
    return JSONResponse({"status": "ok"})


app = Starlette(routes=[
    Route("/bench", bench, methods=["POST"]),
    Route("/health", health),
])

if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=int(os.environ.get("PORT", "8000")))