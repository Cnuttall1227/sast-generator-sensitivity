import os
import json
import uuid
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from wsgiref.simple_server import make_server

import falcon
import jsonpickle

STORAGE_DIR = Path(os.environ.get("FLOORPLAN_STORAGE", "/srv/floorplans"))
API_TOKENS = json.loads(os.environ.get("FLOORPLAN_TOKENS", "{}"))
MAX_BODY_BYTES = 512 * 1024

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("floorplans")


@dataclass
class Room:
    name: str
    x: float
    y: float
    width: float
    depth: float

    def area(self):
        return round(self.width * self.depth, 2)


@dataclass
class FloorPlan:
    title: str
    rooms: list = field(default_factory=list)
    scale_m_per_unit: float = 1.0
    notes: str = ""

    def summary(self):
        areas = [room.area() * self.scale_m_per_unit ** 2 for room in self.rooms]
        return {
            "title": self.title,
            "rooms": len(self.rooms),
            "total_area_m2": round(sum(areas), 2),
            "largest_room": max(self.rooms, key=lambda r: r.area()).name if self.rooms else None,
        }


class AuthMiddleware:
    def process_request(self, req, resp):
        if req.path == "/health":
            return
        token = (req.get_header("Authorization") or "").removeprefix("Bearer ")
        req.context.owner = API_TOKENS.get(token)
        if not req.context.owner:
            raise falcon.HTTPUnauthorized(title="token required")


def decode_plan(body_text):
    plan = jsonpickle.decode(body_text)
    if not isinstance(plan, FloorPlan):
        raise ValueError("document is not a floor plan")
    for room in plan.rooms:
        if not isinstance(room, Room) or room.width <= 0 or room.depth <= 0:
            raise ValueError("every room needs a positive width and depth")
    return plan


def owner_dir(owner):
    path = STORAGE_DIR / "".join(ch for ch in owner if ch.isalnum())
    path.mkdir(parents=True, exist_ok=True)
    return path


def read_body(req):
    if req.content_length and req.content_length > MAX_BODY_BYTES:
        raise falcon.HTTPPayloadTooLarge(title="document too large")
    return req.bounded_stream.read(MAX_BODY_BYTES + 1).decode("utf-8", errors="replace")


class PlanCollection:
    def on_get(self, req, resp):
        plans = []
        for path in sorted(owner_dir(req.context.owner).glob("*.json")):
            plans.append({"id": path.stem, "updated": datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).isoformat()})
        resp.media = {"plans": plans}

    def on_post(self, req, resp):
        text = read_body(req)
        try:
            plan = decode_plan(text)
        except (ValueError, TypeError, KeyError, AttributeError) as exc:
            raise falcon.HTTPBadRequest(title=f"invalid floor plan: {exc}")
        plan_id = uuid.uuid4().hex[:12]
        (owner_dir(req.context.owner) / f"{plan_id}.json").write_text(jsonpickle.encode(plan), encoding="utf-8")
        log.info("%s saved plan %s (%d rooms)", req.context.owner, plan_id, len(plan.rooms))
        resp.status = falcon.HTTP_201
        resp.media = {"id": plan_id, **plan.summary()}


class PlanItem:
    def _path(self, req, plan_id):
        if not plan_id.isalnum():
            raise falcon.HTTPNotFound()
        path = owner_dir(req.context.owner) / f"{plan_id}.json"
        if not path.is_file():
            raise falcon.HTTPNotFound()
        return path

    def on_get(self, req, resp, plan_id):
        plan = decode_plan(self._path(req, plan_id).read_text(encoding="utf-8"))
        resp.media = {"id": plan_id, **plan.summary(),
                      "room_list": [{"name": r.name, "area": r.area()} for r in plan.rooms]}

    def on_delete(self, req, resp, plan_id):
        self._path(req, plan_id).unlink()
        resp.media = {"deleted": plan_id}


class Health:
    def on_get(self, req, resp):
        resp.media = {"status": "ok"}


def create_app():
    app = falcon.App(middleware=[AuthMiddleware()])
    app.add_route("/health", Health())
    app.add_route("/plans", PlanCollection())
    app.add_route("/plans/{plan_id}", PlanItem())
    return app


app = create_app()

if __name__ == "__main__":
    with make_server("127.0.0.1", int(os.environ.get("PORT", "8050")), app) as server:
        log.info("Floor plan service on port %d", server.server_port)
        server.serve_forever()