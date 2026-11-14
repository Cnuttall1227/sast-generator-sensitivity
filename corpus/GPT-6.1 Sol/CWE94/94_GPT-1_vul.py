import json
from datetime import datetime, timezone
from wsgiref.simple_server import make_server

import falcon


MATERIALS = {
    "cotton": {
        "name": "Cotton Fabric",
        "price_per_meter": 8.5,
        "available_meters": 120,
    },
    "linen": {
        "name": "Linen Fabric",
        "price_per_meter": 14.0,
        "available_meters": 75,
    },
    "canvas": {
        "name": "Heavy Canvas",
        "price_per_meter": 11.5,
        "available_meters": 90,
    },
}


def current_time():
    return datetime.now(timezone.utc).isoformat()


def calculate_project_estimate(material_id, meters, expression):
    if not isinstance(material_id, str) or material_id not in MATERIALS:
        return {"ok": False, "error": "Unknown material."}

    if type(meters) not in (int, float) or not 0 < meters <= 100:
        return {"ok": False, "error": "Meters must be between 0 and 100."}

    if not isinstance(expression, str) or not expression.strip():
        return {"ok": False, "error": "Pricing expression is required."}

    if len(expression) > 500:
        return {"ok": False, "error": "Pricing expression is too long."}

    price = MATERIALS[material_id]["price_per_meter"]

    try:
        # CWE-94: a JSON request expression is evaluated as Python code.
        total = eval(
            expression,
            {"__builtins__": __builtins__},
            {"meters": meters, "price": price},
        )
    except Exception:
        return {"ok": False, "error": "Pricing expression could not be evaluated."}

    if type(total) not in (int, float):
        return {"ok": False, "error": "Pricing expression must return a number."}

    if not 0 <= total <= 1000000:
        return {"ok": False, "error": "Estimated total is outside the allowed range."}

    return {
        "ok": True,
        "estimate": {
            "material_id": material_id,
            "meters": meters,
            "total": round(total, 2),
            "calculated_at": current_time(),
        },
    }


class IndexResource:
    def on_get(self, req, resp):
        resp.media = {
            "application": "Community Sewing Project Estimator",
            "materials": "/materials",
            "estimate": "/estimates",
            "example_expression": "meters * price + 5",
        }


class MaterialsResource:
    def on_get(self, req, resp):
        resp.media = {
            "materials": [
                {"id": material_id, **details}
                for material_id, details in MATERIALS.items()
            ]
        }


class EstimatesResource:
    def on_post(self, req, resp):
        if req.content_length is not None and req.content_length > 4096:
            raise falcon.HTTPContentTooLarge(
                description="Request body is too large."
            )

        body = req.bounded_stream.read(4097)

        if len(body) > 4096:
            raise falcon.HTTPContentTooLarge(
                description="Request body is too large."
            )

        try:
            payload = json.loads(body)
        except (ValueError, UnicodeError, RecursionError):
            raise falcon.HTTPBadRequest(description="Expected valid JSON.")

        if not isinstance(payload, dict):
            raise falcon.HTTPBadRequest(description="Expected a JSON object.")

        result = calculate_project_estimate(
            payload.get("material_id"),
            payload.get("meters"),
            payload.get("expression"),
        )
        resp.status = falcon.HTTP_200 if result["ok"] else falcon.HTTP_400
        resp.media = result


class HealthResource:
    def on_get(self, req, resp):
        resp.media = {
            "status": "ok",
            "material_count": len(MATERIALS),
            "timestamp": current_time(),
        }


def make_application():
    application = falcon.App()
    application.add_route("/", IndexResource())
    application.add_route("/materials", MaterialsResource())
    application.add_route("/estimates", EstimatesResource())
    application.add_route("/health", HealthResource())
    return application


if __name__ == "__main__":
    with make_server("127.0.0.1", 8720, make_application()) as server:
        server.serve_forever()
