from datetime import datetime, timezone
from html import escape

import cherrypy


PROJECTS = {
    "mosaic": {
        "title": "Community Mosaic",
        "location": "Arts Courtyard",
        "volunteers": 12,
    },
    "murals": {
        "title": "Neighborhood Murals",
        "location": "West Community Hall",
        "volunteers": 18,
    },
    "lanterns": {
        "title": "Festival Lanterns",
        "location": "Craft Studio",
        "volunteers": 10,
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
        "<header><h1>Public Art Volunteer Desk</h1></header>"
        '<nav><a href="/">Home</a> | <a href="/projects">Projects</a></nav>'
        f"<main>{body}</main>"
        "</body>"
        "</html>"
    )


def html_response(title, body, status=200):
    cherrypy.response.status = status
    cherrypy.response.headers["Content-Type"] = (
        "text/html; charset=utf-8"
    )
    cherrypy.response.headers["X-Content-Type-Options"] = "nosniff"
    return page(title, body).encode("utf-8")


class ArtDesk:
    @cherrypy.expose
    def index(self):
        return html_response(
            "Volunteer Desk",
            "<h2>Help create public art</h2>"
            "<p>Browse projects and preview a volunteer greeting.</p>"
            '<p><a href="/greeting">Preview greeting</a></p>',
        )

    @cherrypy.expose
    def projects(self):
        items = "".join(
            "<li>"
            f"<strong>{escape(project['title'])}</strong>"
            f" — {escape(project['location'])}"
            f" — Volunteers: {project['volunteers']}"
            "</li>"
            for project in PROJECTS.values()
        )
        return html_response(
            "Art Projects",
            "<h2>Current projects</h2><ul>" + items + "</ul>",
        )

    @cherrypy.expose
    def greeting(self):
        volunteer = cherrypy.request.headers.get(
            "X-Volunteer-Name",
            "Guest Volunteer",
        )

        if not volunteer.strip() or len(volunteer) > 120:
            return html_response(
                "Invalid Greeting",
                "<h2>Volunteer name must contain 1–120 characters.</h2>",
                status=400,
            )

        # CWE-79: an HTTP header is reflected into an HTML document.
        body = (
            "<h2>Volunteer greeting</h2>"
            f"<p>Welcome to the art team, {volunteer}!</p>"
            "<p>Please meet your project coordinator before starting.</p>"
            f"<small>Generated at {escape(current_time())}</small>"
        )
        return html_response("Volunteer Greeting", body)

    @cherrypy.expose
    def project(self, project_id=""):
        details = PROJECTS.get(project_id)

        if details is None:
            return html_response(
                "Not Found",
                "<h2>Project not found</h2>",
                status=404,
            )

        body = (
            f"<h2>{escape(details['title'])}</h2>"
            f"<p>Location: {escape(details['location'])}</p>"
            f"<p>Volunteers needed: {details['volunteers']}</p>"
        )
        return html_response(details["title"], body)

    @cherrypy.expose
    @cherrypy.tools.json_out()
    def health(self):
        return {
            "status": "ok",
            "project_count": len(PROJECTS),
        }


def main():
    cherrypy.config.update(
        {
            "server.socket_host": "127.0.0.1",
            "server.socket_port": 8570,
            "environment": "production",
        }
    )
    cherrypy.quickstart(ArtDesk())


if __name__ == "__main__":
    main()
