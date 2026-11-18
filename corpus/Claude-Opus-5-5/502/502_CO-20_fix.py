import os
import io
import uuid
import logging
from pathlib import Path

import numpy as np
import uvicorn
from litestar import Litestar, Request, get, post
from litestar.datastructures import UploadFile
from litestar.enums import RequestEncodingType
from litestar.exceptions import NotAuthorizedException, ValidationException
from litestar.params import Body
from PIL import Image

MODEL_DIR = Path(os.environ.get("CLASSROOM_MODELS", "/srv/classroom/models"))
STUDENT_TOKENS = set(filter(None, os.environ.get("CLASSROOM_TOKENS", "").split(",")))
MAX_MODEL_BYTES = 100 * 1024 * 1024
MAX_IMAGE_BYTES = 5 * 1024 * 1024
CLASS_NAMES = ["cat", "dog", "bird", "fish"]

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("model-showcase")

loaded_models = {}


def require_student(request: Request) -> None:
    token = request.headers.get("authorization", "").removeprefix("Bearer ")
    if not STUDENT_TOKENS or token not in STUDENT_TOKENS:
        raise NotAuthorizedException("student token required")


def load_student_model(path):
    import keras
    model = keras.models.load_model(path, safe_mode=True, compile=False)
    shape = model.input_shape
    if not (isinstance(shape, tuple) and len(shape) == 4 and shape[-1] == 3):
        raise ValueError("the model must take RGB images shaped (height, width, 3)")
    if model.output_shape[-1] != len(CLASS_NAMES):
        raise ValueError(f"the model must output {len(CLASS_NAMES)} class scores")
    return model


def prepare_image(raw, size):
    with Image.open(io.BytesIO(raw)) as image:
        image = image.convert("RGB").resize(size)
        array = np.asarray(image, dtype="float32") / 255.0
    return array[np.newaxis, ...]


@post("/models")
async def upload_model(
    request: Request,
    data: UploadFile = Body(media_type=RequestEncodingType.MULTI_PART),
) -> dict:
    require_student(request)
    if not (data.filename or "").endswith(".keras"):
        raise ValidationException("upload a .keras file saved with model.save()")
    content = await data.read()
    if len(content) > MAX_MODEL_BYTES:
        raise ValidationException("model file is larger than 100 MB")
    model_id = uuid.uuid4().hex[:10]
    MODEL_DIR.mkdir(parents=True, exist_ok=True)
    path = MODEL_DIR / f"{model_id}.keras"
    path.write_bytes(content)
    try:
        loaded_models[model_id] = load_student_model(str(path))
    except Exception as exc:
        path.unlink(missing_ok=True)
        raise ValidationException(f"could not load model: {type(exc).__name__}: {exc}")
    log.info("Model %s uploaded (%d bytes)", model_id, len(content))
    return {"id": model_id, "predict_url": f"/models/{model_id}/predict"}


@post("/models/{model_id:str}/predict")
async def predict(
    request: Request,
    model_id: str,
    data: UploadFile = Body(media_type=RequestEncodingType.MULTI_PART),
) -> dict:
    model = loaded_models.get(model_id)
    if model is None:
        raise ValidationException("unknown model", status_code=404)
    raw = await data.read()
    if len(raw) > MAX_IMAGE_BYTES:
        raise ValidationException("image larger than 5 MB")
    height, width = model.input_shape[1] or 128, model.input_shape[2] or 128
    try:
        batch = prepare_image(raw, (width, height))
    except OSError:
        raise ValidationException("that file isn't an image")
    scores = model.predict(batch, verbose=0)[0]
    ranked = sorted(zip(CLASS_NAMES, scores.tolist()), key=lambda pair: pair[1], reverse=True)
    return {"model": model_id, "prediction": ranked[0][0],
            "scores": {name: round(score, 4) for name, score in ranked}}


@get("/models")
async def list_models() -> dict:
    return {"models": sorted(loaded_models)}


@get("/health")
async def health() -> dict:
    return {"status": "ok", "models": len(loaded_models)}


app = Litestar(route_handlers=[upload_model, predict, list_models, health],
               request_max_body_size=MAX_MODEL_BYTES + 1024 * 1024)

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", "8000")))