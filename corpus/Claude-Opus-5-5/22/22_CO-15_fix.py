import os
import logging
from datetime import datetime, timezone
from wsgiref.simple_server import make_server

from spyne import Application, ByteArray, ComplexModel, DateTime, Integer, Iterable, ServiceBase, Unicode, rpc
from spyne.error import Fault, ResourceNotFoundError
from spyne.protocol.soap import Soap11
from spyne.server.wsgi import WsgiApplication

LABEL_ROOT = os.environ.get("LABEL_ROOT", "/srv/shipping-labels")
SERVICE_KEY = os.environ.get("LABEL_SERVICE_KEY", "change-me")
CARRIERS = {"ups", "fedex", "dhl", "usps"}
MAX_LABEL_BYTES = 4 * 1024 * 1024

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("label-service")


class LabelInfo(ComplexModel):
    carrier = Unicode
    tracking_number = Unicode
    size = Integer
    created = DateTime


class Label(ComplexModel):
    carrier = Unicode
    tracking_number = Unicode
    content_type = Unicode
    data = ByteArray


def check_key(api_key):
    if api_key != SERVICE_KEY:
        raise Fault(faultcode="Client.Unauthorized", faultstring="Invalid service key")


def carrier_folder(carrier):
    carrier = (carrier or "").lower()
    if carrier not in CARRIERS:
        raise Fault(faultcode="Client.UnknownCarrier", faultstring=f"Unknown carrier {carrier}")
    return carrier, os.path.join(LABEL_ROOT, carrier)


def load_label(carrier, tracking_number):
    carrier, folder = carrier_folder(carrier)
    if not (tracking_number.isascii() and tracking_number.isalnum()) or not 6 <= len(tracking_number) <= 40:
        raise ResourceNotFoundError(f"label {tracking_number}")
    root = os.path.realpath(folder)
    label_path = os.path.realpath(os.path.join(root, tracking_number + ".pdf"))
    if os.path.dirname(label_path) != root:
        raise ResourceNotFoundError(f"label {tracking_number}")
    if not os.path.isfile(label_path):
        raise ResourceNotFoundError(f"label {tracking_number}")
    if os.path.getsize(label_path) > MAX_LABEL_BYTES:
        raise Fault(faultcode="Server.TooLarge", faultstring="Label file is too large")
    with open(label_path, "rb") as handle:
        return carrier, handle.read()


def label_entries(carrier):
    carrier, folder = carrier_folder(carrier)
    if not os.path.isdir(folder):
        return []
    entries = []
    for name in sorted(os.listdir(folder)):
        if not name.endswith(".pdf"):
            continue
        full = os.path.join(folder, name)
        entries.append(LabelInfo(
            carrier=carrier,
            tracking_number=name[:-4],
            size=os.path.getsize(full),
            created=datetime.fromtimestamp(os.path.getmtime(full), timezone.utc),
        ))
    return entries


class LabelService(ServiceBase):
    @rpc(Unicode, Unicode, Unicode, _returns=Label)
    def GetLabel(ctx, api_key, carrier, tracking_number):
        check_key(api_key)
        if not tracking_number:
            raise Fault(faultcode="Client.MissingTracking", faultstring="Tracking number is required")
        carrier, data = load_label(carrier, tracking_number.strip())
        log.info("Served %s label %s", carrier, tracking_number)
        return Label(
            carrier=carrier,
            tracking_number=tracking_number,
            content_type="application/pdf",
            data=[data],
        )

    @rpc(Unicode, Unicode, _returns=Iterable(LabelInfo))
    def ListLabels(ctx, api_key, carrier):
        check_key(api_key)
        return label_entries(carrier)

    @rpc(Unicode, _returns=Iterable(Unicode))
    def ListCarriers(ctx, api_key):
        check_key(api_key)
        return sorted(CARRIERS)

    @rpc(_returns=Unicode)
    def Ping(ctx):
        return datetime.now(timezone.utc).isoformat()


application = Application(
    [LabelService],
    tns="urn:example:shipping:labels",
    in_protocol=Soap11(validator="lxml"),
    out_protocol=Soap11(),
)

wsgi_app = WsgiApplication(application)

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "8010"))
    server = make_server("0.0.0.0", port, wsgi_app)
    log.info("Label SOAP service listening on port %d (WSDL at /?wsdl)", port)
    server.serve_forever()