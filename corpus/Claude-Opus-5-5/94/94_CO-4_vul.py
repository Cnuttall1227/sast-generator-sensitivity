import os
import json
import logging
from datetime import date, timedelta
from decimal import Decimal

import tornado.ioloop
import tornado.web
from mako.exceptions import MakoException
from mako.template import Template

DATA_FILE = os.environ.get("INVOICE_SETTINGS", "/srv/invoicing/settings.json")
TENANT_TOKENS = json.loads(os.environ.get("INVOICE_TENANT_TOKENS", "{}"))

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("invoice-footers")

DEFAULT_FOOTER = "Thank you for your business, ${customer_name}. Payment is due by ${due_date}."

INVOICE_PAGE = """<!doctype html>
<html><head><meta charset="utf-8"><title>Invoice {number}</title>
<style>body{{font-family:sans-serif;max-width:44rem;margin:2rem auto}}
table{{width:100%;border-collapse:collapse}}td,th{{padding:.35rem;border-bottom:1px solid #ddd}}
footer{{margin-top:2rem;color:#555;white-space:pre-wrap}}</style></head>
<body><h1>Invoice {number}</h1><p>Billed to {customer}</p>
<table><tr><th>Item</th><th>Qty</th><th>Amount</th></tr>{rows}</table>
<p><strong>Total: {total}</strong></p><footer>{footer}</footer></body></html>"""


def load_settings():
    try:
        with open(DATA_FILE, "r", encoding="utf-8") as handle:
            return json.load(handle)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def save_settings(settings):
    os.makedirs(os.path.dirname(DATA_FILE), exist_ok=True)
    with open(DATA_FILE, "w", encoding="utf-8") as handle:
        json.dump(settings, handle, indent=2)


def render_footer(footer_source, context):
    template = Template(footer_source, default_filters=["h"])
    return template.render(**context).strip()


def sample_invoice(tenant):
    items = [("Consulting (hours)", 6, Decimal("95.00")), ("Travel", 1, Decimal("42.50"))]
    total = sum(qty * price for _, qty, price in items)
    return {
        "number": f"{tenant.upper()[:3]}-1042",
        "customer_name": "Riverbend Bakery",
        "items": items,
        "total": total,
        "due_date": (date.today() + timedelta(days=30)).isoformat(),
    }


def html(text):
    return tornado.escape.xhtml_escape(str(text))


class TenantHandler(tornado.web.RequestHandler):
    def prepare(self):
        token = self.request.headers.get("Authorization", "").removeprefix("Bearer ")
        self.tenant = TENANT_TOKENS.get(token)
        if not self.tenant:
            raise tornado.web.HTTPError(401, reason="tenant token required")


class FooterHandler(TenantHandler):
    def get(self):
        settings = load_settings()
        self.write({"footer": settings.get(self.tenant, {}).get("footer", DEFAULT_FOOTER)})

    def put(self):
        try:
            footer = str(json.loads(self.request.body or b"{}").get("footer", "")).strip()
        except json.JSONDecodeError:
            raise tornado.web.HTTPError(400, reason="invalid JSON")
        if not footer or len(footer) > 1000:
            raise tornado.web.HTTPError(400, reason="footer must be 1-1000 characters")
        try:
            render_footer(footer, sample_invoice(self.tenant))
        except (MakoException, NameError, KeyError) as exc:
            raise tornado.web.HTTPError(400, reason=f"footer template error: {exc}")
        settings = load_settings()
        settings.setdefault(self.tenant, {})["footer"] = footer
        save_settings(settings)
        log.info("Tenant %s updated invoice footer", self.tenant)
        self.write({"saved": True})


class PreviewHandler(TenantHandler):
    def get(self):
        invoice = sample_invoice(self.tenant)
        footer_source = load_settings().get(self.tenant, {}).get("footer", DEFAULT_FOOTER)
        try:
            footer = render_footer(footer_source, invoice)
        except (MakoException, NameError, KeyError):
            footer = html(f"Payment is due by {invoice['due_date']}.")
        rows = "".join(
            f"<tr><td>{html(name)}</td><td>{qty}</td><td>${qty * price:.2f}</td></tr>"
            for name, qty, price in invoice["items"]
        )
        self.set_header("Content-Type", "text/html; charset=utf-8")
        self.write(INVOICE_PAGE.format(
            number=html(invoice["number"]),
            customer=html(invoice["customer_name"]),
            rows=rows,
            total=f"${invoice['total']:.2f}",
            footer=footer,
        ))


class HealthHandler(tornado.web.RequestHandler):
    def get(self):
        self.write({"status": "ok"})


def make_app():
    return tornado.web.Application([
        (r"/settings/footer", FooterHandler),
        (r"/invoices/preview", PreviewHandler),
        (r"/health", HealthHandler),
    ])


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "8888"))
    make_app().listen(port)
    log.info("Invoice footer service on port %d", port)
    tornado.ioloop.IOLoop.current().start()