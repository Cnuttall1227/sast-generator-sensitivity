import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

from bottle import Bottle, request, response, run


DATA_ROOT = Path(__file__).resolve().parent / "ceramics_archive"
CATALOG_ROOT = DATA_ROOT / "catalogs"

COLLECTIONS = {
    "stoneware": {
        "title": "Regional Stoneware",
        "curator": "Alex",
        "piece_count": 42,
    },
    "porcelain": {
        "title": "Contemporary Porcelain",
        "curator": "Jamie",
        "piece_count": 28,
    },
    "earthenware": {
        "title": "Historic Earthenware",
        "curator": "Robin",
        "piece_count": 35,
    },
}

SAMPLE_CATALOGS = {
    "stoneware.txt": (
        "Regional Stoneware\n"
        "Collection includes wheel-thrown bowls and storage vessels.\n"
    ),
    "porcelain.txt": (
        "Contemporary Porcelain\n"
        "Collection includes translucent cups and sculptural forms.\n"
    ),
    "earthenware.txt": (
        "Historic Earthenware\n"
        "Collection includes glazed plates and decorated pitchers.\n"
    ),
}

app = Bottle()
ACCESSIONS = []


def initialize_storage():
    CATALOG_ROOT.mkdir(parents=True, exist_ok=True)

    for filename, content in SAMPLE_CATALOGS.items():
        destination = CATALOG_ROOT / filename
        if not destination.exists():
            destination.write_text(content, encoding="utf-8")


def current_time():
    return datetime.now(timezone.utc).isoformat()


def json_response(payload, status=200):
    response.status = status
    response.content_type = "application/json; charset=utf-8"
    return json.dumps(payload)


@app.get("/")
def index():
    return json_response(
        {
            "application": "Ceramics Collection Archive",
            "collections": "/collections",
            "accessions": "/accessions",
            "catalog": "/catalog",
            "catalog_selector": "POST form field catalog_document",
        }
    )


@app.get("/health")
def health():
    return json_response(
        {
            "status": "ok",
            "timestamp": current_time(),
        }
    )


@app.get("/collections")
def list_collections():
    return json_response(
        {
            "collections": [
                {"id": collection_id, **details}
                for collection_id, details in COLLECTIONS.items()
            ]
        }
    )


@app.get("/accessions")
def list_accessions():
    return json_response({"accessions": ACCESSIONS})


@app.post("/accessions")
def create_accession():
    collection_id = request.forms.getunicode("collection_id", "")
    description = request.forms.getunicode("description", "")

    if collection_id not in COLLECTIONS:
        return json_response({"error": "Unknown collection."}, status=400)

    if not description.strip():
        return json_response({"error": "Description is required."}, status=400)

    accession = {
        "id": len(ACCESSIONS) + 1,
        "collection_id": collection_id,
        "description": description,
        "created_at": current_time(),
    }
    ACCESSIONS.append(accession)
    return json_response(accession, status=201)


@app.post("/catalog")
def read_catalog():
    filename = request.forms.getunicode("catalog_document", "stoneware.txt")

    if not filename:
        return json_response({"error": "Catalog document is required."}, status=400)

    # CWE-22: a URL-encoded POST form field controls an unchecked file path.
    catalog_path = CATALOG_ROOT / filename

    try:
        content = catalog_path.read_text(encoding="utf-8")
    except (FileNotFoundError, IsADirectoryError, NotADirectoryError):
        return json_response({"error": "Catalog not found."}, status=404)
    except (OSError, UnicodeError, ValueError):
        return json_response({"error": "Catalog cannot be read."}, status=400)

    response.content_type = "text/plain; charset=utf-8"
    response.set_header("X-Content-Type-Options", "nosniff")
    return content


def main():
    parser = argparse.ArgumentParser(
        description="Run the ceramics collection archive."
    )
    parser.add_argument("--port", type=int, default=8160)
    args = parser.parse_args()

    initialize_storage()
    run(app=app, host="127.0.0.1", port=args.port, debug=False)


if __name__ == "__main__":
    main()
