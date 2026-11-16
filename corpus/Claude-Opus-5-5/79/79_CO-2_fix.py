import os
import re
import sqlite3
import logging
from datetime import datetime, timezone

import uvicorn
from fastapi import FastAPI, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from jinja2 import DictLoader, Environment, select_autoescape
from markupsafe import Markup
from markupsafe import escape

DB_PATH = os.environ.get("RECIPE_DB", "/srv/recipes/recipes.db")
MAX_COMMENT_LENGTH = 2000
URL_PATTERN = re.compile(r"(https?://[^\s<]+)")

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("recipes")

TEMPLATES = {
    "base.html": """<!doctype html>
<html><head><meta charset="utf-8"><title>{% block title %}Recipes{% endblock %}</title></head>
<body style="font-family:sans-serif;max-width:46rem;margin:2rem auto">
<p><a href="/">All recipes</a></p>
{% block content %}{% endblock %}
</body></html>""",
    "index.html": """{% extends "base.html" %}{% block content %}
<h1>Recipes</h1>
<ul>{% for r in recipes %}<li><a href="/recipes/{{ r.id }}">{{ r.title }}</a> ({{ r.comments }} comments)</li>{% endfor %}</ul>
{% endblock %}""",
    "recipe.html": """{% extends "base.html" %}{% block title %}{{ recipe.title }}{% endblock %}
{% block content %}
<h1>{{ recipe.title }}</h1>
<p>{{ recipe.description }}</p>
<h2>Comments</h2>
{% for c in comments %}
<div class="comment"><strong>{{ c.author }}</strong> <small>{{ c.created_at }}</small>
<p>{{ c.body_html }}</p></div>
{% else %}<p>No comments yet.</p>{% endfor %}
<h3>Add a comment</h3>
<form method="post" action="/recipes/{{ recipe.id }}/comments">
<input name="author" placeholder="Your name" maxlength="60" required><br>
<textarea name="body" rows="4" cols="60" maxlength="2000" required></textarea><br>
<button type="submit">Post</button>
</form>
{% endblock %}""",
}

env = Environment(loader=DictLoader(TEMPLATES), autoescape=select_autoescape(default=True))
app = FastAPI(title="Recipe comments")


def db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    with db() as conn:
        conn.executescript(
            """CREATE TABLE IF NOT EXISTS recipes (
                   id INTEGER PRIMARY KEY, title TEXT NOT NULL, description TEXT NOT NULL);
               CREATE TABLE IF NOT EXISTS comments (
                   id INTEGER PRIMARY KEY AUTOINCREMENT, recipe_id INTEGER NOT NULL,
                   author TEXT NOT NULL, body TEXT NOT NULL, created_at TEXT NOT NULL);"""
        )


def format_comment(body):
    paragraphs = body.replace("\r\n", "\n").split("\n\n")
    rendered = []
    for paragraph in paragraphs:
        pieces = []
        for index, part in enumerate(URL_PATTERN.split(paragraph)):
            if index % 2 == 1:
                url = escape(part)
                pieces.append(f'<a href="{url}" rel="nofollow noopener">{url}</a>')
            else:
                pieces.append(str(escape(part)).replace("\n", "<br>"))
        rendered.append("".join(pieces))
    return Markup("</p><p>".join(rendered))

def render(name, **context):
    return HTMLResponse(env.get_template(name).render(**context))


@app.on_event("startup")
def startup():
    init_db()


@app.get("/", response_class=HTMLResponse)
def index():
    with db() as conn:
        recipes = conn.execute(
            """SELECT r.id, r.title, COUNT(c.id) AS comments FROM recipes r
               LEFT JOIN comments c ON c.recipe_id = r.id GROUP BY r.id ORDER BY r.title"""
        ).fetchall()
    return render("index.html", recipes=recipes)


@app.get("/recipes/{recipe_id}", response_class=HTMLResponse)
def show_recipe(recipe_id: int):
    with db() as conn:
        recipe = conn.execute("SELECT * FROM recipes WHERE id = ?", (recipe_id,)).fetchone()
        if recipe is None:
            raise HTTPException(status_code=404, detail="Recipe not found")
        rows = conn.execute(
            "SELECT author, body, created_at FROM comments WHERE recipe_id = ? ORDER BY id",
            (recipe_id,),
        ).fetchall()
    comments = [
        {"author": r["author"], "created_at": r["created_at"][:16].replace("T", " "),
         "body_html": format_comment(r["body"])}
        for r in rows
    ]
    return render("recipe.html", recipe=recipe, comments=comments)


@app.post("/recipes/{recipe_id}/comments")
def add_comment(recipe_id: int, request: Request, author: str = Form(...), body: str = Form(...)):
    author, body = author.strip()[:60], body.strip()[:MAX_COMMENT_LENGTH]
    if not author or not body:
        raise HTTPException(status_code=400, detail="Name and comment are required")
    with db() as conn:
        if conn.execute("SELECT 1 FROM recipes WHERE id = ?", (recipe_id,)).fetchone() is None:
            raise HTTPException(status_code=404, detail="Recipe not found")
        conn.execute(
            "INSERT INTO comments (recipe_id, author, body, created_at) VALUES (?, ?, ?, ?)",
            (recipe_id, author, body, datetime.now(timezone.utc).isoformat()),
        )
    log.info("New comment on recipe %d from %s", recipe_id, request.client.host if request.client else "?")
    return RedirectResponse(f"/recipes/{recipe_id}", status_code=303)


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", "8000")))