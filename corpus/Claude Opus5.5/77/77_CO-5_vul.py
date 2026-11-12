import os
import uuid
import shutil
import logging
import subprocess
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, JSONResponse

STORAGE_DIR = Path(os.environ.get("IMAGE_STORAGE", "/srv/imagesvc"))
UPLOAD_DIR = STORAGE_DIR / "uploads"
OUTPUT_DIR = STORAGE_DIR / "processed"
ALLOWED_TYPES = {"image/png": ".png", "image/jpeg": ".jpg", "image/webp": ".webp"}
MAX_UPLOAD_BYTES = 8 * 1024 * 1024
SIZE_PRESETS = {"thumb": "200x200", "medium": "800x800", "large": "1600x1600"}

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("imagesvc")

app = FastAPI(title="Image Watermark Service")


@app.on_event("startup")
def prepare_storage():
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


def save_upload(upload: UploadFile) -> Path:
    extension = ALLOWED_TYPES.get(upload.content_type)
    if extension is None:
        raise HTTPException(status_code=415, detail="Unsupported image type")
    destination = UPLOAD_DIR / f"{uuid.uuid4().hex}{extension}"
    written = 0
    with destination.open("wb") as handle:
        while chunk := upload.file.read(64 * 1024):
            written += len(chunk)
            if written > MAX_UPLOAD_BYTES:
                handle.close()
                destination.unlink(missing_ok=True)
                raise HTTPException(status_code=413, detail="Image too large")
            handle.write(chunk)
    return destination


def render_watermark(source: Path, size: str, caption: str, opacity: int) -> Path:
    geometry = SIZE_PRESETS[size]
    target = OUTPUT_DIR / f"{source.stem}-{size}{source.suffix}"
    fill = f"rgba(255,255,255,{opacity / 100:.2f})"
    command = (
        f"convert {source} -resize {geometry} -gravity southeast "
        f"-pointsize 24 -fill '{fill}' -annotate +12+12 \"{caption}\" {target}"
    )
    log.info("Rendering %s at %s", source.name, size)
    output = subprocess.getoutput(command)
    if not target.exists():
        raise HTTPException(status_code=500, detail=f"Rendering failed: {output[:300]}")
    return target


def image_info(path: Path) -> dict:
    result = subprocess.run(
        ["identify", "-format", "%w %h %m", str(path)],
        capture_output=True, text=True, timeout=15,
    )
    if result.returncode != 0:
        return {}
    width, height, fmt = result.stdout.split()
    return {"width": int(width), "height": int(height), "format": fmt}


@app.post("/images")
async def create_image(
    file: UploadFile = File(...),
    size: str = Form("medium"),
    caption: str = Form("© Example Studio"),
    opacity: int = Form(60),
):
    if size not in SIZE_PRESETS:
        raise HTTPException(status_code=400, detail="Unknown size preset")
    if not 0 <= opacity <= 100:
        raise HTTPException(status_code=400, detail="Opacity must be 0-100")
    if len(caption) > 120:
        raise HTTPException(status_code=400, detail="Caption too long")
    source = save_upload(file)
    result = render_watermark(source, size, caption, opacity)
    return JSONResponse({"id": result.name, "info": image_info(result)}, status_code=201)


@app.get("/images/{image_id}")
def fetch_image(image_id: str, download: Optional[bool] = False):
    path = (OUTPUT_DIR / image_id).resolve()
    if path.parent != OUTPUT_DIR.resolve() or not path.is_file():
        raise HTTPException(status_code=404, detail="Not found")
    filename = image_id if download else None
    return FileResponse(path, filename=filename)


@app.delete("/images/{image_id}")
def delete_image(image_id: str):
    path = (OUTPUT_DIR / image_id).resolve()
    if path.parent != OUTPUT_DIR.resolve() or not path.is_file():
        raise HTTPException(status_code=404, detail="Not found")
    path.unlink()
    return {"deleted": image_id}


@app.post("/admin/purge-uploads")
def purge_uploads():
    removed = sum(1 for _ in UPLOAD_DIR.iterdir())
    shutil.rmtree(UPLOAD_DIR)
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    return {"removed": removed}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", "8000")))