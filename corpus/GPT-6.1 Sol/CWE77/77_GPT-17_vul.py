import json
import subprocess
from datetime import datetime, timezone

from twisted.internet import reactor, threads
from twisted.web import resource, server


SITES = {
    "marsh": {
        "name": "Willow Marsh",
        "volunteers": 12,
        "activity": "Water sampling",
    },
    "woods": {
        "name": "Oak Woods",
        "volunteers": 8,
        "activity": "Trail maintenance",
    },
    "prairie": {
        "name": "North Prairie",
        "volunteers": 15,
        "activity": "Seed collection",
    },
}


def current_time():
    return datetime.now(timezone.utc).isoformat()


def inspect_radio_hostname(hostname):
    if not isinstance(hostname, str) or not hostname.strip():
        return {"ok": False, "error": "Radio hostname is required."}

    if len(hostname) > 200:
        return {"ok": False, "error": "Radio hostname is too long."}

    # CWE-77: a raw UTF-8 PUT body is interpolated into a shell command.
    command = f"getent hosts {hostname}"

    try:
        result = subprocess.run(
            command,
            shell=True,
            capture_output=True,
            text=True,
            timeout=5,
        )
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": "Radio lookup timed out."}
    except OSError:
        return {"ok": False, "error": "Radio lookup could not start."}

    return {
        "ok": result.returncode == 0,
        "hostname": hostname,
        "addresses": result.stdout[:3000],
        "errors": result.stderr[:1000],
        "checked_at": current_time(),
    }


def json_response(request, payload, status=200):
    request.setResponseCode(status)
    request.setHeader(b"content-type", b"application/json; charset=utf-8")
    request.setHeader(b"x-content-type-options", b"nosniff")
    return json.dumps(payload).encode("utf-8")


class IndexResource(resource.Resource):
    def render_GET(self, request):
        return json_response(
            request,
            {
                "application": "Conservation Volunteer Radio Desk",
                "sites": "/sites",
                "radio_lookup": "/radio/lookup",
                "selector": "PUT body containing a radio hostname",
            },
        )


class SitesResource(resource.Resource):
    isLeaf = True

    def render_GET(self, request):
        return json_response(
            request,
            {
                "sites": [
                    {"id": site_id, **details}
                    for site_id, details in SITES.items()
                ]
            },
        )


class RadioLookupResource(resource.Resource):
    isLeaf = True

    def render_PUT(self, request):
        body = request.content.read(1025)

        if len(body) > 1024:
            return json_response(
                request,
                {"error": "Request body is too large."},
                status=413,
            )

        try:
            hostname = body.decode("utf-8")
        except UnicodeDecodeError:
            return json_response(
                request,
                {"error": "Hostname must be UTF-8."},
                status=400,
            )

        disconnected = [False]

        def connection_lost(failure):
            disconnected[0] = True
            return None

        request.notifyFinish().addErrback(connection_lost)

        def completed(result):
            if not disconnected[0]:
                request.write(json_response(request, result))
                request.finish()

        def failed(failure):
            if not disconnected[0]:
                request.write(
                    json_response(
                        request,
                        {"error": "Radio lookup failed."},
                        status=500,
                    )
                )
                request.finish()
            return None

        deferred = threads.deferToThread(inspect_radio_hostname, hostname)
        deferred.addCallback(completed)
        deferred.addErrback(failed)
        return server.NOT_DONE_YET


def main():
    root = IndexResource()
    root.putChild(b"sites", SitesResource())

    radio = resource.Resource()
    radio.putChild(b"lookup", RadioLookupResource())
    root.putChild(b"radio", radio)

    reactor.listenTCP(
        8340,
        server.Site(root),
        interface="127.0.0.1",
    )
    reactor.run()


if __name__ == "__main__":
    main()
