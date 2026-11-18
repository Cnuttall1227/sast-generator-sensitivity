import os
import logging
from datetime import date

from quart import Quart, abort, render_template_string, request

SITE_NAME = os.environ.get("CARDS_SITE_NAME", "Kindly Cards")
OCCASIONS = {
    "birthday": {"title": "Happy Birthday", "color": "#f4a261", "emoji": "🎂"},
    "thanks": {"title": "Thank You", "color": "#2a9d8f", "emoji": "💐"},
    "congrats": {"title": "Congratulations", "color": "#e9c46a", "emoji": "🎉"},
    "get-well": {"title": "Get Well Soon", "color": "#8ab17d", "emoji": "🌼"},
}
MAX_NAME_LENGTH = 40

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("cards")

app = Quart(__name__)

BASE_LAYOUT = """<!doctype html>
<html><head><meta charset="utf-8"><title>{{ page_title }} – {{ site }}</title>
<style>
body { font-family: Georgia, serif; background: #faf7f2; margin: 0; }
.card { max-width: 30rem; margin: 4rem auto; padding: 3rem 2rem; text-align: center;
        background: white; border-top: 12px solid {{ color }}; box-shadow: 0 6px 24px #0002; }
.emoji { font-size: 3rem; } h1 { margin: .5rem 0; } .from { color: #666; margin-top: 2rem; }
form { max-width: 30rem; margin: 2rem auto; } label { display: block; margin: .6rem 0; }
</style></head><body>__CONTENT__</body></html>"""

INDEX_CONTENT = """<form action="/make" method="get">
<h1>{{ site }}</h1>
<label>Who is it for? <input name="to" maxlength="40" required></label>
<label>From <input name="from" maxlength="40"></label>
<label>Occasion <select name="occasion">
{% for key, occ in occasions.items() %}<option value="{{ key }}">{{ occ.title }}</option>{% endfor %}
</select></label>
<button type="submit">Make a card</button></form>"""


def clean_name(raw):
    name = " ".join(raw.split())[:MAX_NAME_LENGTH]
    return name


def build_card_template(recipient, sender):
    sender_line = f'<p class="from">With love, {sender}</p>' if sender else ""
    content = (
        '<div class="card"><div class="emoji">{{ emoji }}</div>'
        f"<h1>{{{{ title }}}}, {recipient}!</h1>"
        "<p>Wishing you a wonderful {{ today.strftime('%A') }}.</p>"
        f"{sender_line}"
        '<p><a href="/">Make your own card</a></p></div>'
    )
    return BASE_LAYOUT.replace("__CONTENT__", content)


@app.get("/")
async def index():
    template = BASE_LAYOUT.replace("__CONTENT__", INDEX_CONTENT)
    return await render_template_string(
        template, site=SITE_NAME, page_title="Make a card", color="#999", occasions=OCCASIONS
    )


@app.get("/make")
async def make():
    recipient = clean_name(request.args.get("to", ""))
    occasion = request.args.get("occasion", "birthday")
    if not recipient or occasion not in OCCASIONS:
        abort(400)
    sender = clean_name(request.args.get("from", ""))
    query = f"?from={sender}" if sender else ""
    return "", 302, {"Location": f"/card/{occasion}/{recipient}{query}"}


@app.get("/card/<occasion>/<recipient>")
async def card(occasion, recipient):
    details = OCCASIONS.get(occasion)
    if details is None:
        abort(404)
    recipient = clean_name(recipient)
    sender = clean_name(request.args.get("from", ""))
    if not recipient:
        abort(404)
    template = build_card_template(recipient, sender)
    log.info("Rendered %s card", occasion)
    return await render_template_string(
        template,
        site=SITE_NAME,
        page_title=details["title"],
        title=details["title"],
        color=details["color"],
        emoji=details["emoji"],
        today=date.today(),
        recipient=recipient,
        sender=sender,
    )


@app.get("/health")
async def health():
    return {"status": "ok"}


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "5000")))