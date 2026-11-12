import os
import json
import hmac
import logging
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Annotated

import uvicorn
from litestar import Litestar, Request, get
from litestar.exceptions import NotAuthorizedException, NotFoundException, ValidationException
from litestar.params import Parameter
from litestar.response import File

INVOICE_ROOT = os.environ.get("INVOICE_ROOT", "/srv/invoices")
GATEWAY_SECRET = os.environ.get("GATEWAY_SECRET", "change-me")
TENANT_PATTERN = re.compile(r"^[a-z0-9][a-z0-9_-]{0,62}$")
INVOICE_ID_LENGTH = 12

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("invoice-api")


def verify_gateway(request: Request) -> None:
    supplied = request.headers.get("X-Gateway-Secret", "")
    if not hmac.compare_digest(supplied, GATEWAY_SECRET):
        raise NotAuthorizedException("Requests must come through the API gateway")


def valid_invoice_id(invoice_id: str) -> bool:
    return len(invoice_id) == INVOICE_ID_LENGTH and invoice_id.isalnum() and invoice_id.isupper()


def tenant_directory(tenant_id: str) -> str:
    if not TENANT_PATTERN.fullmatch(tenant_id or ""):
        raise NotFoundException("Unknown tenant")
    root = os.path.realpath(INVOICE_ROOT)
    directory = os.path.realpath(os.path.join(root, tenant_id))
    if os.path.dirname(directory) != root or not os.path.isdir(directory):
        raise NotFoundException("Unknown tenant")
    return directory


def read_index(directory: str) -> list:
    index_path = os.path.join(directory, "index.json")
    try:
        with open(index_path, "r", encoding="utf-8") as handle:
            return json.load(handle).get("invoices", [])
    except (FileNotFoundError, json.JSONDecodeError):
        return []


def invoice_summary(entry: dict) -> dict:
    return {
        "id": entry.get("id"),
        "number": entry.get("number"),
        "issued": entry.get("issued"),
        "total": entry.get("total"),
        "currency": entry.get("currency", "USD"),
        "status": entry.get("status", "open"),
    }


@get("/health")
async def health() -> dict:
    return {"status": "ok", "time": datetime.now(timezone.utc).isoformat()}


@get("/invoices")
async def list_invoices(
    request: Request,
    tenant_id: Annotated[str, Parameter(header="X-Tenant-ID")],
    status: Annotated[str | None, Parameter(query="status")] = None,
) -> dict:
    verify_gateway(request)
    directory = tenant_directory(tenant_id)
    invoices = [invoice_summary(e) for e in read_index(directory)]
    if status:
        invoices = [i for i in invoices if i["status"] == status]
    return {"tenant": tenant_id, "count": len(invoices), "invoices": invoices}


@get("/invoices/{invoice_id:str}")
async def get_invoice(
    request: Request,
    invoice_id: str,
    tenant_id: Annotated[str, Parameter(header="X-Tenant-ID")],
) -> dict:
    verify_gateway(request)
    if not valid_invoice_id(invoice_id):
        raise ValidationException("Invalid invoice id")
    directory = tenant_directory(tenant_id)
    for entry in read_index(directory):
        if entry.get("id") == invoice_id:
            return invoice_summary(entry)
    raise NotFoundException("Invoice not found")


@get("/invoices/{invoice_id:str}/pdf")
async def download_invoice(
    request: Request,
    invoice_id: str,
    tenant_id: Annotated[str, Parameter(header="X-Tenant-ID")],
) -> File:
    verify_gateway(request)
    if not valid_invoice_id(invoice_id):
        raise ValidationException("Invalid invoice id")
    directory = tenant_directory(tenant_id)
    pdf_path = Path(directory) / f"{invoice_id}.pdf"
    if not pdf_path.is_file():
        raise NotFoundException("Invoice PDF not found")
    log.info("Tenant %s downloaded %s", tenant_id, invoice_id)
    return File(path=pdf_path, filename=f"invoice-{invoice_id}.pdf", media_type="application/pdf")


app = Litestar(route_handlers=[health, list_invoices, get_invoice, download_invoice])

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", "8000")))