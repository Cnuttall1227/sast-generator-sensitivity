from datetime import datetime, timezone
from html import escape

import tornado.ioloop
import tornado.web


EVENTS = {
    "meteor": {
        "title": "Meteor Shower Watch",
        "location": "North Field",
        "capacity": 40,
    },
    "moon": {
        "title": "Moon Photography Night",
        "location": "Roof Terrace",
        "capacity": 18,
    },
    "planets": {
        "title": "Planet Spotting Workshop",
        "location": "Observatory Lawn",
        "capacity": 25,
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
        "<header><h1>Community Stargazing Club</h1></header>"
        '<nav><a href="/">Home</a> | <a href="/events">Events</a></nav>'
        f"<main>{body}</main>"
        "</body>"
        "</html>"
    )


class BaseHandler(tornado.web.RequestHandler):
    def set_default_headers(self):
        self.set_header("X-Content-Type-Options", "nosniff")

    def write_html(self, title, body, status=200):
        self.set_status(status)
        self.set_header("Content-Type", "text/html; charset=utf-8")
        self.finish(page(title, body))


class IndexHandler(BaseHandler):
    def get(self):
        body = (
            "<h2>Plan your next observing night</h2>"
            "<p>Browse upcoming events and preview your observer badge.</p>"
            '<p><a href="/badge">Preview observer badge</a></p>'
            '<form action="/preferences" method="post">'
            '<label>Observer name: <input name="observer" maxlength="100"></label>'
            '<button type="submit">Save badge name</button>'
            "</form>"
        )
        self.write_html("Stargazing Club", body)


class EventsHandler(BaseHandler):
    def get(self):
        items = "".join(
            "<li>"
            f"<strong>{escape(event['title'])}</strong>"
            f" — {escape(event['location'])}"
            f" — Capacity: {event['capacity']}"
            "</li>"
            for event in EVENTS.values()
        )
        self.write_html("Upcoming Events", f"<h2>Events</h2><ul>{items}</ul>")


class PreferencesHandler(BaseHandler):
    def post(self):
        observer = self.get_body_argument("observer", "").strip()

        if not observer or len(observer) > 100:
            self.write_html(
                "Invalid Name",
                "<h2>Enter an observer name of 1–100 characters.</h2>",
                status=400,
            )
            return

        self.set_cookie(
            "observer_name",
            observer,
            httponly=True,
            samesite="Lax",
        )
        self.redirect("/badge")


class BadgeHandler(BaseHandler):
    def get(self):
        observer = self.get_cookie("observer_name", default="Guest Observer")

        if len(observer) > 100:
            self.write_html(
                "Invalid Badge",
                "<h2>Observer name is too long.</h2>",
                status=400,
            )
            return

        body = (
            "<h2>Observer badge</h2>"
            '<section class="badge">'
            f"<p>Observer: {escape(observer)}</p>"
            "<p>Community Stargazing Club</p>"
            "</section>"
            f"<small>Generated at {escape(current_time())}</small>"
        )
        self.write_html("Observer Badge", body)


class HealthHandler(BaseHandler):
    def get(self):
        self.set_header("Content-Type", "application/json")
        self.finish({"status": "ok", "event_count": len(EVENTS)})


def main():
    application = tornado.web.Application(
        [
            (r"/", IndexHandler),
            (r"/events", EventsHandler),
            (r"/preferences", PreferencesHandler),
            (r"/badge", BadgeHandler),
            (r"/health", HealthHandler),
        ],
        debug=False,
    )
    application.listen(8540, address="127.0.0.1")
    tornado.ioloop.IOLoop.current().start()


if __name__ == "__main__":
    main()
