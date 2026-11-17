from datetime import datetime, timezone
from html import escape

from quart import Quart, jsonify


app = Quart(__name__)

ITEMS = {
    "umbrella": {
        "name": "Blue Umbrella",
        "found_at": "Main Entrance",
        "category": "Accessories",
    },
    "notebook": {
        "name": "Green Notebook",
        "found_at": "Reading Room",
        "category": "Stationery",
    },
    "scarf": {
        "name": "Striped Scarf",
        "found_at": "Community Hall",
        "category": "Clothing",
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
        "<header><h1>Neighborhood Lost Property Desk</h1></header>"
        '<nav><a href="/">Home</a> | '
        '<a href="/items">Found items</a> | '
        '<a href="/claim-card">Claim card</a></nav>'
        f"<main>{body}</main>"
        "</body>"
        "</html>"
    )


def html_response(title, body, status=200):
    return (
        page(title, body),
        status,
        {
            "Content-Type": "text/html; charset=utf-8",
            "X-Content-Type-Options": "nosniff",
        },
    )


@app.get("/")
async def index():
    return html_response(
        "Lost Property Desk",
        "<h2>Find a missing belonging</h2>"
        "<p>Browse items handed in by community members.</p>"
        "<p>Create a claim card before visiting the information desk.</p>"
        '<p><a href="/claim-card#Guest">Preview a sample claim card</a></p>',
    )


@app.get("/items")
async def list_items():
    entries = []

    for item_id, details in ITEMS.items():
        entries.append(
            "<li>"
            f"<strong>{escape(details['name'])}</strong>"
            f" — Found at {escape(details['found_at'])}"
            f' — <a href="/items/{escape(item_id, quote=True)}">Details</a>'
            "</li>"
        )

    return html_response(
        "Found Items",
        "<h2>Items awaiting collection</h2><ul>"
        + "".join(entries)
        + "</ul>",
    )


@app.get("/items/<item_id>")
async def item_details(item_id):
    details = ITEMS.get(item_id)

    if details is None:
        return html_response(
            "Not Found",
            "<h2>Item not found.</h2>",
            status=404,
        )

    body = (
        f"<h2>{escape(details['name'])}</h2>"
        f"<p>Found at: {escape(details['found_at'])}</p>"
        f"<p>Category: {escape(details['category'])}</p>"
        "<p>Please describe identifying features when collecting this item.</p>"
    )
    return html_response("Item Details", body)


@app.get("/claim-card")
async def claim_card():
    body = (
        "<h2>Property claim card</h2>"
        '<section class="claim-card">'
        '<p>Claimant: <span id="claimant"></span></p>'
        "<p>Bring this card to the information desk.</p>"
        "</section>"
        "<script>"
        "function updateClaimant() {"
        "  let name;"
        "  try {"
        "    name = decodeURIComponent(window.location.hash.slice(1));"
        "  } catch (error) {"
        "    name = 'Guest';"
        "  }"
        "  if (!name.trim() || name.length > 200) {"
        "    name = 'Guest';"
        "  }"
        "  document.getElementById('claimant').textContent = name;"
        "}"
        "window.addEventListener('hashchange', updateClaimant);"
        "updateClaimant();"
        "</script>"
        f"<small>Generated at {escape(current_time())}</small>"
    )
    return html_response("Claim Card", body)


@app.get("/health")
async def health():
    return jsonify(
        status="ok",
        item_count=len(ITEMS),
        timestamp=current_time(),
    )


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=8660, debug=False)
