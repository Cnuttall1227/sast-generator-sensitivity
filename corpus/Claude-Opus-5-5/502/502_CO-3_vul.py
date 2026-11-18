import io
import os
import json
import logging

import numpy as np
from aiohttp import web

API_KEYS = set(filter(None, os.environ.get("SIGNAL_API_KEYS", "").split(",")))
MAX_UPLOAD_BYTES = 50 * 1024 * 1024
MAX_SAMPLES = 10_000_000

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("vibration-analyzer")


def require_key(request):
    if not API_KEYS or request.headers.get("X-Api-Key", "") not in API_KEYS:
        raise web.HTTPUnauthorized(text="API key required")


def load_recording(raw_bytes):
    loaded = np.load(io.BytesIO(raw_bytes), allow_pickle=True)
    if isinstance(loaded, np.lib.npyio.NpzFile):
        if "signal" not in loaded.files:
            raise ValueError("the .npz file must contain an array named 'signal'")
        signal = loaded["signal"]
        sample_rate = float(loaded["sample_rate"]) if "sample_rate" in loaded.files else None
    else:
        signal, sample_rate = loaded, None
    signal = np.asarray(signal, dtype=float)
    if signal.ndim != 1:
        raise ValueError("signal must be one-dimensional")
    if not 16 <= signal.size <= MAX_SAMPLES:
        raise ValueError(f"signal must have 16 to {MAX_SAMPLES:,} samples")
    return signal, sample_rate


def analyze(signal, sample_rate):
    centered = signal - signal.mean()
    rms = float(np.sqrt(np.mean(centered ** 2)))
    peak = float(np.max(np.abs(centered)))
    crest = peak / rms if rms else 0.0
    spectrum = np.abs(np.fft.rfft(centered * np.hanning(centered.size)))
    freqs = np.fft.rfftfreq(centered.size, d=1.0 / sample_rate)
    top = np.argsort(spectrum[1:])[-5:][::-1] + 1
    return {
        "samples": int(signal.size),
        "duration_s": round(signal.size / sample_rate, 3),
        "rms": round(rms, 6),
        "peak": round(peak, 6),
        "crest_factor": round(crest, 3),
        "dominant_frequencies_hz": [round(float(freqs[i]), 2) for i in top],
        "alert": crest > 6 or rms > 2.5,
    }


async def analyze_upload(request):
    require_key(request)
    reader = await request.multipart()
    field = await reader.next()
    if field is None or field.name != "recording":
        raise web.HTTPBadRequest(text="send the file in a 'recording' form field")
    chunks, size = [], 0
    while True:
        chunk = await field.read_chunk(1024 * 1024)
        if not chunk:
            break
        size += len(chunk)
        if size > MAX_UPLOAD_BYTES:
            raise web.HTTPRequestEntityTooLarge(max_size=MAX_UPLOAD_BYTES, actual_size=size)
        chunks.append(chunk)
    try:
        sample_rate_param = float(request.query.get("sample_rate", "0") or 0)
    except ValueError:
        raise web.HTTPBadRequest(text="sample_rate must be a number")
    try:
        signal, embedded_rate = load_recording(b"".join(chunks))
    except (ValueError, OSError, EOFError) as exc:
        raise web.HTTPBadRequest(text=f"could not read recording: {exc}")
    sample_rate = embedded_rate or sample_rate_param
    if not sample_rate or sample_rate <= 0 or sample_rate > 1_000_000:
        raise web.HTTPBadRequest(text="provide a sample_rate (Hz) in the file or query string")
    result = analyze(signal, sample_rate)
    log.info("Analyzed %s: %d samples, alert=%s", field.filename, result["samples"], result["alert"])
    return web.json_response(result)


async def health(request):
    return web.json_response({"status": "ok", "numpy": np.__version__})


def create_app():
    app = web.Application(client_max_size=MAX_UPLOAD_BYTES + 1024 * 1024)
    app.router.add_get("/health", health)
    app.router.add_post("/analyze", analyze_upload)
    return app


if __name__ == "__main__":
    web.run_app(create_app(), host="127.0.0.1", port=int(os.environ.get("PORT", "8080")))