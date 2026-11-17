import json
import subprocess
from datetime import datetime, timezone
from wsgiref.simple_server import make_server

import falcon


ROUTES = {
    "riverside": {
        "name": "Riverside Delivery Route",
        "distance_km": 8,
        "stops": 12,
    },
    "uptown": {
        "name": "Uptown Delivery Route",
        "distance_km": 11,
        "stops": 16,
    },
    "market": {
        "name": "Market Delivery Route",
        "distance_km": 5,
        "stops": 9,
    },
}

DISPATCHES = []


def current_time():
    return datetime.now(timezone.utc).isoformat()


def inspect_network_interface(interface_name):
    if not isinstance(interface_name, str) or not interface_name.strip():
        return {"ok": False, "error": "Network interface is required."}

    if len(interface_name) > 100:
        return {"ok": False, "error": "Interface name is too long."}

    # CWE-77: a URL path parameter is inserted into a shell command.
    command = f"ip -details link show dev {interface_name}"

    try:
        result = subprocess.run(
            command,
            shell=True,
            capture_output=True,
            text=True,
            timeout=5,
        )
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": "Interface inspection timed out."}
    except OSError:
        return {"ok": False, "error": "Interface inspection could not start."}

    return {
        "ok": result.returncode == 0,
        "interface": interface_name,
        "details": result.stdout[:4000],
        "errors": result.stderr[:1000],
        "checked_at": current_time(),
    }


class IndexResource:
    def on_get(self, req, resp):
        resp.media = {
            "application": "Bicycle Courier Dispatch Desk",
            "routes": "/routes",
            "dispatches": "/dispatches",
            "network_check": "/network/interfaces/{interface_name}",
        }


class RoutesResource:
    def on_get(self, req, resp):
        resp.media = {
            "routes": [
                {"id": route_id, **details}
                for route_id, details in ROUTES.items()
            ]
        }


class DispatchesResource:
    def on_get(self, req, resp):
        resp.media = {"dispatches": DISPATCHES}

    def on_post(self, req, resp):
        payload = req.get_media()

        if not isinstance(payload, dict):
            raise falcon.HTTPBadRequest(
                description="Expected a JSON object."
            )

        route_id = payload.get("route_id")
        courier = payload.get("courier")

        if not isinstance(route_id, str) or route_id not in ROUTES:
            raise falcon.HTTPBadRequest(description="Unknown route.")

        if not isinstance(courier, str) or not courier.strip():
            raise falcon.HTTPBadRequest(
                description="Courier name is required."
            )

        dispatch = {
            "id": len(DISPATCHES) + 1,
            "route_id": route_id,
            "courier": courier,
            "created_at": current_time(),
        }
        DISPATCHES.append(dispatch)
        resp.status = falcon.HTTP_201
        resp.media = dispatch


class InterfaceResource:
    def on_get(self, req, resp, interface_name):
        resp.media = inspect_network_interface(interface_name)
        resp.set_header("X-Content-Type-Options", "nosniff")


class HealthResource:
    def on_get(self, req, resp):
        resp.media = {
            "status": "ok",
            "timestamp": current_time(),
            "route_count": len(ROUTES),
        }


def make_application():
    application = falcon.App()
    application.add_route("/", IndexResource())
    application.add_route("/routes", RoutesResource())
    application.add_route("/dispatches", DispatchesResource())
    application.add_route(
        "/network/interfaces/{interface_name}",
        InterfaceResource(),
    )
    application.add_route("/health", HealthResource())
    return application


def main():
    with make_server(
        "127.0.0.1",
        8290,
        make_application(),
    ) as server:
        print(json.dumps({"host": "127.0.0.1", "port": 8290}))
        server.serve_forever()


if __name__ == "__main__":
    main()
