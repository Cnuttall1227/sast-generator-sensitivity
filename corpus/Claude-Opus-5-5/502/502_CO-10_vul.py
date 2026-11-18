import os
import json
import uuid
import pickle
import logging
import threading
from concurrent import futures
from dataclasses import dataclass, field
from datetime import datetime, timezone

import grpc

LISTEN = os.environ.get("PRINTQ_LISTEN", "127.0.0.1:50081")
AUTH_TOKEN = os.environ.get("PRINTQ_TOKEN", "")
SERVICE_NAME = "printq.PrintQueue"
PRINTERS = {"front-desk": "HP LaserJet M404", "studio": "Epson SureColor P900", "warehouse": "Zebra ZT411"}
MAX_DOCUMENT_BYTES = 30 * 1024 * 1024

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("print-queue")


@dataclass
class PrintOptions:
    copies: int = 1
    duplex: bool = False
    color: bool = True
    paper: str = "letter"
    pages: list = field(default_factory=list)


jobs = {}
jobs_lock = threading.Lock()


def encode(message):
    return json.dumps(message).encode("utf-8")


def decode(raw):
    return json.loads(raw.decode("utf-8")) if raw else {}


def check_auth(context):
    metadata = dict(context.invocation_metadata())
    if not AUTH_TOKEN or metadata.get("authorization") != f"Bearer {AUTH_TOKEN}":
        context.abort(grpc.StatusCode.UNAUTHENTICATED, "invalid token")


def read_options(encoded_options):
    if not encoded_options:
        return PrintOptions()
    options = pickle.loads(bytes.fromhex(encoded_options))
    if not isinstance(options, PrintOptions):
        raise ValueError("options must be a PrintOptions object")
    if not 1 <= options.copies <= 50:
        raise ValueError("copies must be 1-50")
    if options.paper not in ("letter", "legal", "a4", "label-4x6"):
        raise ValueError("unsupported paper size")
    return options


class PrintQueueService:
    def Submit(self, request, context):
        check_auth(context)
        printer = str(request.get("printer", ""))
        if printer not in PRINTERS:
            context.abort(grpc.StatusCode.INVALID_ARGUMENT, f"printer must be one of {', '.join(PRINTERS)}")
        document_hex = str(request.get("document_hex", ""))
        if not document_hex or len(document_hex) > MAX_DOCUMENT_BYTES * 2:
            context.abort(grpc.StatusCode.INVALID_ARGUMENT, "document is missing or too large")
        try:
            options = read_options(request.get("options_hex", ""))
        except Exception as exc:
            context.abort(grpc.StatusCode.INVALID_ARGUMENT, f"bad options: {exc}")
        job_id = uuid.uuid4().hex[:10]
        with jobs_lock:
            jobs[job_id] = {
                "id": job_id,
                "printer": printer,
                "title": str(request.get("title", "Untitled"))[:120],
                "bytes": len(document_hex) // 2,
                "copies": options.copies,
                "duplex": options.duplex,
                "color": options.color,
                "paper": options.paper,
                "status": "queued",
                "submitted_at": datetime.now(timezone.utc).isoformat(),
            }
        log.info("Queued job %s on %s (%d copies)", job_id, printer, options.copies)
        return {"id": job_id, "position": self._position(job_id)}

    def _position(self, job_id):
        with jobs_lock:
            queued = [j for j in jobs.values() if j["status"] == "queued"]
            return next((i for i, j in enumerate(queued, 1) if j["id"] == job_id), 0)

    def Status(self, request, context):
        check_auth(context)
        with jobs_lock:
            job = jobs.get(str(request.get("id", "")))
        if job is None:
            context.abort(grpc.StatusCode.NOT_FOUND, "unknown job")
        return job

    def Cancel(self, request, context):
        check_auth(context)
        with jobs_lock:
            job = jobs.get(str(request.get("id", "")))
            if job is None:
                context.abort(grpc.StatusCode.NOT_FOUND, "unknown job")
            if job["status"] != "queued":
                context.abort(grpc.StatusCode.FAILED_PRECONDITION, "job already printing")
            job["status"] = "cancelled"
        return {"id": job["id"], "status": "cancelled"}

    def Printers(self, request, context):
        check_auth(context)
        return {"printers": [{"id": k, "model": v} for k, v in PRINTERS.items()]}


def build_server():
    service = PrintQueueService()
    handlers = {name: grpc.unary_unary_rpc_method_handler(getattr(service, name), decode, encode)
                for name in ("Submit", "Status", "Cancel", "Printers")}
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=8))
    server.add_generic_rpc_handlers((grpc.method_handlers_generic_handler(SERVICE_NAME, handlers),))
    server.add_insecure_port(LISTEN)
    return server


if __name__ == "__main__":
    server = build_server()
    server.start()
    log.info("Print queue listening on %s", LISTEN)
    server.wait_for_termination()