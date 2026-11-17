import os
import logging
from datetime import datetime, timezone

import uvicorn
from fastapi import Depends, FastAPI, Header, HTTPException
from jinja2 import Environment, TemplateSyntaxError, select_autoescape
from pydantic import BaseModel, Field

ADMIN_TOKENS = set(filter(None, os.environ.get("NOTIFY_ADMIN_TOKENS", "").split(",")))

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("notify-templates")

app = FastAPI(title="Notification templates")

templates = {
    "order_shipped": {
        "subject": "Your order {{ order.number }} is on its way",
        "body": "Hi {{ customer.first_name }},\n\nYour order shipped on {{ order.shipped_on }} "
                "via {{ order.carrier }}. Tracking: {{ order.tracking }}.\n\nThanks!",
    },
    "password_reset": {
        "subject": "Reset your password",
        "body": "Hi {{ customer.first_name }}, use this link within 30 minutes: {{ reset_link }}",
    },
}

SAMPLE_CONTEXT = {
    "customer": {"first_name": "Avery", "last_name": "Lee", "email": "avery@example.com"},
    "order": {
        "number": "A-10492",
        "shipped_on": "2026-11-14",
        "carrier": "UPS",
        "tracking": "1Z999AA10123456784",
        "total": "84.20",
    },
    "reset_link": "https://example.com/reset/sample-token",
    "store_name": "Northwind Outfitters",
}


class TemplateIn(BaseModel):
    subject: str = Field(min_length=1, max_length=200)
    body: str = Field(min_length=1, max_length=10000)


class PreviewIn(BaseModel):
    subject: str = Field(min_length=1, max_length=200)
    body: str = Field(min_length=1, max_length=10000)
    context: dict = Field(default_factory=dict)


def require_admin(authorization: str = Header(default="")):
    token = authorization.removeprefix("Bearer ").strip()
    if not ADMIN_TOKENS or token not in ADMIN_TOKENS:
        raise HTTPException(status_code=401, detail="admin token required")
    return token


def render_template_text(source, context, autoescape=False):
    env = Environment(autoescape=select_autoescape(default=autoescape), trim_blocks=True)
    template = env.from_string(source)
    return template.render(**context)


def render_message(subject_source, body_source, context):
    merged = {**SAMPLE_CONTEXT, **context}
    try:
        subject = render_template_text(subject_source, merged).strip()
        body = render_template_text(body_source, merged)
    except TemplateSyntaxError as exc:
        raise HTTPException(status_code=400, detail=f"template error on line {exc.lineno}: {exc.message}")
    if "\n" in subject:
        raise HTTPException(status_code=400, detail="subject must be a single line")
    return {"subject": subject, "body": body}


@app.get("/health")
def health():
    return {"status": "ok", "templates": len(templates)}


@app.get("/templates")
def list_templates(_admin: str = Depends(require_admin)):
    return {"templates": templates}


@app.put("/templates/{name}")
def save_template(name: str, data: TemplateIn, _admin: str = Depends(require_admin)):
    if not name.replace("_", "").isalnum() or len(name) > 40:
        raise HTTPException(status_code=400, detail="template names may use letters, digits and _")
    render_message(data.subject, data.body, {})
    templates[name] = {"subject": data.subject, "body": data.body}
    log.info("Saved template %s", name)
    return {"name": name, "saved_at": datetime.now(timezone.utc).isoformat()}


@app.post("/templates/preview")
def preview(data: PreviewIn, _admin: str = Depends(require_admin)):
    return render_message(data.subject, data.body, data.context)


@app.post("/templates/{name}/render")
def render_named(name: str, context: dict, _admin: str = Depends(require_admin)):
    template = templates.get(name)
    if template is None:
        raise HTTPException(status_code=404, detail="unknown template")
    return render_message(template["subject"], template["body"], context)


if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=int(os.environ.get("PORT", "8000")))