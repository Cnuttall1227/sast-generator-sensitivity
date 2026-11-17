import html
import logging
from datetime import datetime

import gradio as gr
from PIL import ExifTags, Image

MAX_PIXELS = 60_000_000
TAG_NAMES = {tag_id: name for tag_id, name in ExifTags.TAGS.items()}
GPS_NAMES = {tag_id: name for tag_id, name in ExifTags.GPSTAGS.items()}
SHOWN_TAGS = [
    "Make", "Model", "LensModel", "DateTimeOriginal", "ExposureTime", "FNumber",
    "ISOSpeedRatings", "FocalLength", "Artist", "Copyright", "ImageDescription", "Software",
]

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("exif-inspector")

TABLE_STYLE = """
<style>
.exif-table { border-collapse: collapse; width: 100%; font-size: .95rem; }
.exif-table th, .exif-table td { border-bottom: 1px solid #ddd; padding: .4rem .6rem; text-align: left; }
.exif-table th { width: 35%; color: #555; font-weight: 600; }
.exif-warning { background: #fff4e5; border-left: 4px solid #f0a020; padding: .6rem .8rem; margin-top: .75rem; }
</style>
"""


def format_value(value):
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace").strip("\x00 ")
    if isinstance(value, tuple) and len(value) == 2 and all(isinstance(v, int) for v in value):
        return f"{value[0]}/{value[1]}" if value[1] else str(value[0])
    if hasattr(value, "numerator") and hasattr(value, "denominator"):
        return f"{float(value):.4g}"
    return str(value)


def gps_to_decimal(coords, ref):
    degrees, minutes, seconds = (float(c) for c in coords)
    decimal = degrees + minutes / 60 + seconds / 3600
    return -decimal if ref in ("S", "W") else decimal


def read_metadata(image):
    exif = image.getexif()
    fields = {}
    for tag_id, value in exif.items():
        name = TAG_NAMES.get(tag_id)
        if name:
            fields[name] = format_value(value)
    for tag_id, value in exif.get_ifd(0x8769).items():
        name = TAG_NAMES.get(tag_id)
        if name:
            fields[name] = format_value(value)
    gps = {GPS_NAMES.get(k, k): v for k, v in exif.get_ifd(0x8825).items()}
    location = None
    if "GPSLatitude" in gps and "GPSLongitude" in gps:
        try:
            location = (
                gps_to_decimal(gps["GPSLatitude"], gps.get("GPSLatitudeRef", "N")),
                gps_to_decimal(gps["GPSLongitude"], gps.get("GPSLongitudeRef", "E")),
            )
        except (TypeError, ValueError, ZeroDivisionError):
            location = None
    return fields, location


def render_metadata_table(fields, location, size, image_format):
    rows = [
        f"<tr><th>Format</th><td>{html.escape(image_format or 'unknown')}</td></tr>",
        f"<tr><th>Dimensions</th><td>{int(size[0])} × {int(size[1])} px</td></tr>",
    ]
    for name in SHOWN_TAGS:
        value = fields.get(name)
        if value:
            value = str(value)
            if len(value) > 200:
                value = value[:200] + "…"
            rows.append(f"<tr><th>{html.escape(name)}</th><td>{html.escape(value)}</td></tr>")
    warning = ""
    if location:
        lat, lon = location
        rows.append(f"<tr><th>GPS position</th><td>{float(lat):.5f}, {float(lon):.5f}</td></tr>")
        warning = (
            "<div class='exif-warning'>This photo contains GPS coordinates. "
            "Remove them before sharing if the location is private.</div>"
        )
    return f"{TABLE_STYLE}<table class='exif-table'>{''.join(rows)}</table>{warning}"


def inspect_photo(path):
    if not path:
        return "<p>Upload a photo to see its metadata.</p>", None
    try:
        with Image.open(path) as image:
            if image.width * image.height > MAX_PIXELS:
                return "<p>That image is too large to inspect.</p>", None
            fields, location = read_metadata(image)
            table = render_metadata_table(fields, location, image.size, image.format)
            clean = image.copy()
    except (OSError, Image.DecompressionBombError) as exc:
        log.warning("Could not read upload: %s", exc)
        return "<p>That file doesn't look like a supported image.</p>", None
    stripped_path = f"/tmp/stripped-{datetime.now():%Y%m%d%H%M%S%f}.png"
    clean.save(stripped_path, format="PNG")
    log.info("Inspected image with %d EXIF field(s)", len(fields))
    return table, stripped_path


with gr.Blocks(title="Photo metadata inspector") as demo:
    gr.Markdown("# Photo metadata inspector\nSee what your photo reveals before you post it.")
    with gr.Row():
        photo = gr.Image(type="filepath", label="Photo", sources=["upload"])
        with gr.Column():
            report = gr.HTML("<p>Upload a photo to see its metadata.</p>")
            cleaned = gr.File(label="Copy with metadata removed")
    photo.change(inspect_photo, inputs=photo, outputs=[report, cleaned])

if __name__ == "__main__":
    demo.launch(server_name="127.0.0.1", server_port=7860)