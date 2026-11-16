import os
import json
import time
import logging
from collections import deque
from concurrent import futures

import grpc

LOG_ROOT = os.environ.get("LOGSVC_ROOT", "/var/log/apps")
LISTEN = os.environ.get("LOGSVC_LISTEN", "[::]:50051")
AUTH_TOKEN = os.environ.get("LOGSVC_TOKEN", "change-me")
MAX_LINES = 1000
SERVICE_NAME = "logs.LogService"

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("log-service")


def encode(message):
    return json.dumps(message).encode("utf-8")


def decode(raw):
    return json.loads(raw.decode("utf-8"))


def check_auth(context):
    metadata = dict(context.invocation_metadata())
    if metadata.get("authorization") != f"Bearer {AUTH_TOKEN}":
        context.abort(grpc.StatusCode.UNAUTHENTICATED, "invalid token")


def app_log_dir(app):
    if not app or not app.replace("-", "").isalnum():
        raise ValueError("app names may contain letters, digits and -")
    path = os.path.join(LOG_ROOT, app)
    if not os.path.isdir(path):
        raise LookupError(f"no logs for {app}")
    return path


def open_log(app, file_name):
    if not file_name or file_name in (".", "..") or "/" in file_name or "\\" in file_name or "\x00" in file_name:
        raise LookupError(f"no log file {file_name}")
    directory = os.path.realpath(app_log_dir(app))
    path = os.path.realpath(os.path.join(directory, file_name))
    if os.path.dirname(path) != directory or not os.path.isfile(path):
        raise LookupError(f"no log file {file_name}")
    return open(path, "r", encoding="utf-8", errors="replace")


def list_log_files(app):
    directory = app_log_dir(app)
    files = []
    for name in sorted(os.listdir(directory)):
        full = os.path.join(directory, name)
        if os.path.isfile(full):
            files.append({"name": name, "bytes": os.path.getsize(full), "modified": int(os.path.getmtime(full))})
    return files


class LogService:
    def ListApps(self, request, context):
        check_auth(context)
        apps = sorted(d for d in os.listdir(LOG_ROOT) if os.path.isdir(os.path.join(LOG_ROOT, d)))
        return {"apps": apps}

    def ListFiles(self, request, context):
        check_auth(context)
        try:
            return {"app": request.get("app"), "files": list_log_files(str(request.get("app", "")))}
        except ValueError as exc:
            context.abort(grpc.StatusCode.INVALID_ARGUMENT, str(exc))
        except LookupError as exc:
            context.abort(grpc.StatusCode.NOT_FOUND, str(exc))

    def Tail(self, request, context):
        check_auth(context)
        app = str(request.get("app", ""))
        file_name = str(request.get("file", "current.log"))
        lines = max(1, min(int(request.get("lines", 100)), MAX_LINES))
        try:
            with open_log(app, file_name) as handle:
                tail = list(deque(handle, maxlen=lines))
        except ValueError as exc:
            context.abort(grpc.StatusCode.INVALID_ARGUMENT, str(exc))
        except LookupError as exc:
            context.abort(grpc.StatusCode.NOT_FOUND, str(exc))
        return {"app": app, "file": file_name, "lines": [line.rstrip("\n") for line in tail]}

    def Follow(self, request, context):
        check_auth(context)
        app = str(request.get("app", ""))
        file_name = str(request.get("file", "current.log"))
        try:
            handle = open_log(app, file_name)
        except ValueError as exc:
            context.abort(grpc.StatusCode.INVALID_ARGUMENT, str(exc))
        except LookupError as exc:
            context.abort(grpc.StatusCode.NOT_FOUND, str(exc))
        with handle:
            handle.seek(0, os.SEEK_END)
            while context.is_active():
                line = handle.readline()
                if line:
                    yield {"line": line.rstrip("\n")}
                else:
                    time.sleep(0.5)


def build_server():
    service = LogService()
    handlers = {
        "ListApps": grpc.unary_unary_rpc_method_handler(service.ListApps, decode, encode),
        "ListFiles": grpc.unary_unary_rpc_method_handler(service.ListFiles, decode, encode),
        "Tail": grpc.unary_unary_rpc_method_handler(service.Tail, decode, encode),
        "Follow": grpc.unary_stream_rpc_method_handler(service.Follow, decode, encode),
    }
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=8))
    server.add_generic_rpc_handlers((grpc.method_handlers_generic_handler(SERVICE_NAME, handlers),))
    server.add_insecure_port(LISTEN)
    return server


if __name__ == "__main__":
    server = build_server()
    server.start()
    log.info("Log service listening on %s", LISTEN)
    try:
        server.wait_for_termination()
    except KeyboardInterrupt:
        server.stop(grace=5)