from datetime import datetime, timezone
from html import escape
from wsgiref.simple_server import make_server

import falcon


RECIPES = {
    "soup": {
        "title": "Roasted Vegetable Soup",
        "minutes": 45,
        "category": "Lunch",
    },
    "bread": {
        "title": "Wholegrain Soda Bread",
        "minutes": 50,
        "category": "Baking",
    },
    "salad": {
        "title": "Seasonal Bean Salad",
        "minutes": 20,
        "category": "Lunch",
    },
}

COMMENTS = []


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
        "<header><h1>Community Recipe Exchange</h1></header>"
        '<nav><a href="/">Home</a> | <a href="/recipes">Recipes</a>'
        ' | <a href="/comments">Comments</a></nav>'
        f"<main>{body}</main>"
        "</body>"
        "</html>"
    )


def write_html(resp, title, body, status=falcon.HTTP_200):
    resp.status = status
    resp.content_type = "text/html; charset=utf-8"
    resp.set_header("X-Content-Type-Options", "nosniff")
    resp.text = page(title, body)


class IndexResource:
    def on_get(self, req, resp):
        write_html(
            resp,
            "Recipe Exchange",
            "<h2>Cook and share</h2>"
            "<p>Browse recipes and leave a cooking note.</p>"
            '<form action="/comments" method="post">'
            '<label>Your name: <input name="author" maxlength="80"></label>'
            '<label>Comment: <textarea name="comment" maxlength="500">'
            "</textarea></label>"
            '<button type="submit">Post comment</button>'
            "</form>",
        )


class RecipesResource:
    def on_get(self, req, resp):
        items = "".join(
            "<li>"
            f"<strong>{escape(recipe['title'])}</strong>"
            f" — {recipe['minutes']} minutes"
            f" — {escape(recipe['category'])}"
            "</li>"
            for recipe in RECIPES.values()
        )
        write_html(resp, "Recipes", f"<h2>Recipes</h2><ul>{items}</ul>")


class CommentsResource:
    def on_post(self, req, resp):
        fields = req.get_media()

        if not isinstance(fields, dict):
            raise falcon.HTTPBadRequest(description="Expected form fields.")

        author = fields.get("author", "")
        comment = fields.get("comment", "")

        if not isinstance(author, str) or not 1 <= len(author.strip()) <= 80:
            raise falcon.HTTPBadRequest(description="Invalid author name.")

        if not isinstance(comment, str) or not 1 <= len(comment.strip()) <= 500:
            raise falcon.HTTPBadRequest(description="Invalid comment.")

        COMMENTS.append(
            {
                "author": author.strip(),
                "comment": comment.strip(),
                "created_at": current_time(),
            }
        )
        resp.status = falcon.HTTP_303
        resp.set_header("Location", "/comments")

    def on_get(self, req, resp):
        # CWE-79: stored comments are inserted into HTML without escaping.
        entries = "".join(
            "<article>"
            f"<h3>{escape(entry['author'])}</h3>"
            f"<p>{entry['comment']}</p>"
            f"<small>{escape(entry['created_at'])}</small>"
            "</article>"
            for entry in COMMENTS
        )
        write_html(
            resp,
            "Cooking Comments",
            "<h2>Cooking comments</h2>" + entries,
        )


class HealthResource:
    def on_get(self, req, resp):
        resp.media = {
            "status": "ok",
            "recipe_count": len(RECIPES),
            "comment_count": len(COMMENTS),
        }


def make_application():
    application = falcon.App()
    application.add_route("/", IndexResource())
    application.add_route("/recipes", RecipesResource())
    application.add_route("/comments", CommentsResource())
    application.add_route("/health", HealthResource())
    return application


if __name__ == "__main__":
    with make_server("127.0.0.1", 8550, make_application()) as server:
        server.serve_forever()
