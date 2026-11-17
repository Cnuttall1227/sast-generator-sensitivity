from datetime import datetime, timezone
from html import escape

from flask import Flask, Response, jsonify, request


app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 8192

BOOKS = {
    "atlas": {
        "title": "An Atlas of Imaginary Places",
        "author": "Rowan Bell",
        "category": "Travel",
    },
    "orchard": {
        "title": "The Orchard Notebook",
        "author": "Mira Lane",
        "category": "Nature",
    },
    "clockmaker": {
        "title": "The Clockmaker's Window",
        "author": "Avery North",
        "category": "Fiction",
    },
}


def current_time():
    return datetime.now(timezone.utc).isoformat()


def html_response(content, status=200):
    return Response(
        content,
        status=status,
        content_type="text/html; charset=utf-8",
        headers={"X-Content-Type-Options": "nosniff"},
    )


def page(title, body):
    return (
        "<!doctype html>"
        '<html lang="en">'
        "<head>"
        '<meta charset="utf-8">'
        f"<title>{escape(title)}</title>"
        "</head>"
        "<body>"
        "<header><h1>Neighborhood Book Exchange</h1></header>"
        '<nav><a href="/">Home</a> | <a href="/books">Books</a></nav>'
        f"<main>{body}</main>"
        "</body>"
        "</html>"
    )


@app.get("/")
def index():
    body = (
        "<h2>Find your next book</h2>"
        '<form action="/search" method="get">'
        '<label>Search titles: <input name="q" maxlength="100"></label>'
        '<button type="submit">Search</button>'
        "</form>"
    )
    return html_response(page("Book Exchange", body))


@app.get("/books")
def list_books():
    items = []

    for book_id, book in BOOKS.items():
        items.append(
            "<li>"
            f"<strong>{escape(book['title'])}</strong>"
            f" by {escape(book['author'])}"
            f" — {escape(book['category'])}"
            f' — <a href="/books/{escape(book_id, quote=True)}">Details</a>'
            "</li>"
        )

    return html_response(
        page("Books", "<h2>Available books</h2><ul>" + "".join(items) + "</ul>")
    )


@app.get("/books/<book_id>")
def book_details(book_id):
    book = BOOKS.get(book_id)

    if book is None:
        return html_response(
            page("Not Found", "<h2>Book not found</h2>"),
            status=404,
        )

    body = (
        f"<h2>{escape(book['title'])}</h2>"
        f"<p>Author: {escape(book['author'])}</p>"
        f"<p>Category: {escape(book['category'])}</p>"
    )
    return html_response(page(book["title"], body))


@app.get("/search")
def search_books():
    query = request.args.get("q", "").strip()

    if len(query) > 100:
        return html_response(
            page(
                "Invalid Search",
                "<h2>Search text must be 100 characters or fewer.</h2>",
            ),
            status=400,
        )

    matches = [
        book
        for book in BOOKS.values()
        if query.casefold() in book["title"].casefold()
    ]
    items = "".join(
        f"<li>{escape(book['title'])} by {escape(book['author'])}</li>"
        for book in matches
    )

    body = (
        "<h2>Search results</h2>"
        '<form action="/search" method="get">'
        f'<input name="q" value="{escape(query, quote=True)}" maxlength="100">'
        '<button type="submit">Search again</button>'
        "</form>"
        f"<p>Matches: {len(matches)}</p>"
        f"<ul>{items}</ul>"
    )
    return html_response(page("Search Results", body))


@app.get("/health")
def health():
    return jsonify(
        status="ok",
        timestamp=current_time(),
        book_count=len(BOOKS),
    )


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=8530, debug=False)
