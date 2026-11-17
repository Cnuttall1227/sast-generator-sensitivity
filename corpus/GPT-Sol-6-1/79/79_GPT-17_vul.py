import json
from datetime import datetime, timezone
from html import escape

from twisted.internet import reactor
from twisted.web import resource, server


SERVICES = {
    "hemming": {
        "title": "Trouser Hemming",
        "station": "Sewing Table One",
        "minutes": 30,
    },
    "patching": {
        "title": "Visible Mending",
        "station": "Sewing Table Two",
        "minutes": 45,
    },
    "buttons": {
        "title": "Button Replacement",
        "station": "Hand Sewing Corner",
        "minutes": 15,
    },
}


def current_time():
    return datetime.now(timezone.utc).isoformat()


def page(title, body):
    return (
        "<!doctype html>"
        '<html lang="en">'
        "<head>"
        '<meta charset="utf-8">'
        f"<title>{escape(title)}</title>"
        "</head>"
        "<body>"
        "<header><h1>Community Clothing Repair Desk</h1></header>"
        '<nav><a href="/">Home</a> | <a href="/services">Services</a></nav>'
        f"<main>{body}</main>"
        "</body>"
        "</html>"
    )


def html_response(request, title, body, status=200):
    request.setResponseCode(status)
    request.setHeader(b"content-type", b"text/html; charset=utf-8")
    request.setHeader(b"x-content-type-options", b"nosniff")
    return page(title, body).encode("utf-8")


class IndexResource(resource.Resource):
    def render_GET(self, request):
        return html_response(
            request,
            "Clothing Repair",
            "<h2>Give clothing a second life</h2>"
            "<p>Browse repair services and prepare an intake tag.</p>"
            "<p>Send a JSON object in the X-Repair-Tag header to /tag.</p>",
        )


class ServicesResource(resource.Resource):
    isLeaf = True

    def render_GET(self, request):
        entries = "".join(
            "<li>"
            f"<strong>{escape(service['title'])}</strong>"
            f" — {escape(service['station'])}"
            f" — {service['minutes']} minutes"
            "</li>"
            for service in SERVICES.values()
        )
        return html_response(
            request,
            "Repair Services",
            "<h2>Available services</h2><ul>" + entries + "</ul>",
        )


class TagResource(resource.Resource):
    isLeaf = True

    def render_GET(self, request):
        raw_tag = request.getHeader("X-Repair-Tag") or '{"owner":"Guest"}'

        if len(raw_tag) > 2048:
            return html_response(
                request,
                "Invalid Tag",
                "<h2>Tag header is too large.</h2>",
                status=400,
            )

        try:
            tag = json.loads(raw_tag)
        except (ValueError, UnicodeError, RecursionError):
            return html_response(
                request,
                "Invalid Tag",
                "<h2>Expected valid JSON in the tag header.</h2>",
                status=400,
            )

        if not isinstance(tag, dict):
            return html_response(
                request,
                "Invalid Tag",
                "<h2>Tag must contain an object.</h2>",
                status=400,
            )

        owner = tag.get("owner")

        if not isinstance(owner, str) or not 1 <= len(owner.strip()) <= 120:
            return html_response(
                request,
                "Invalid Tag",
                "<h2>Owner must contain 1–120 characters.</h2>",
                status=400,
            )

        # CWE-79: a JSON-valued header reaches a quoted HTML attribute.
        body = (
            "<h2>Clothing intake tag</h2>"
            "<label>Owner name:"
            f'<input name="owner" value="{owner}" readonly>'
            "</label>"
            "<p>Please attach this tag to your repair bag.</p>"
            f"<small>Generated at {escape(current_time())}</small>"
        )
        return html_response(request, "Intake Tag", body)


class HealthResource(resource.Resource):
    isLeaf = True

    def render_GET(self, request):
        request.setHeader(b"content-type", b"application/json")
        return json.dumps(
            {
                "status": "ok",
                "service_count": len(SERVICES),
            }
        ).encode("utf-8")


def main():
    root = IndexResource()
    root.putChild(b"services", ServicesResource())
    root.putChild(b"tag", TagResource())
    root.putChild(b"health", HealthResource())
    reactor.listenTCP(8680, server.Site(root), interface="127.0.0.1")
    reactor.run()


if __name__ == "__main__":
    main()
