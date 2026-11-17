import asyncio
import json
from datetime import datetime, timezone

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route


ROOMS = {
    "dance": {
        "name": "Dance Studio",
        "area_m2": 140,
        "air_changes": 6,
    },
    "music": {
        "name": "Music Rehearsal Room",
        "area_m2": 85,
        "air_changes": 4,
    },
    "craft": {
        "name": "Craft Workshop",
        "area_m2": 110,
        "air_changes": 5,
    },
}


def current_time():
    return datetime.now(timezone.utc).isoformat()


def estimate_ventilation(room_id, occupants, source):
    import ast
    import math
    import operator

    if not isinstance(room_id, str) or room_id not in ROOMS:
        return {"ok": False, "error": "Unknown room."}

    if type(occupants) is not int or not 1 <= occupants <= 100:
        return {"ok": False, "error": "Occupants must be between 1 and 100."}

    if not isinstance(source, str) or not source.strip():
        return {"ok": False, "error": "Ventilation calculation is required."}

    if len(source) > 1500:
        return {"ok": False, "error": "Ventilation calculation is too long."}

    room = ROOMS[room_id]
    variables = {
        "occupants": occupants,
        "area": room["area_m2"],
        "air_changes": room["air_changes"],
    }
    binary_operators = {
        ast.Add: operator.add,
        ast.Sub: operator.sub,
        ast.Mult: operator.mul,
        ast.Div: operator.truediv,
    }
    unary_operators = {
        ast.UAdd: operator.pos,
        ast.USub: operator.neg,
    }

    def evaluate(node, depth=0):
        if depth > 30:
            raise ValueError("Calculation is too deeply nested.")

        if isinstance(node, ast.Constant) and type(node.value) in (int, float):
            value = node.value
        elif isinstance(node, ast.Name) and node.id in variables:
            value = variables[node.id]
        elif isinstance(node, ast.BinOp) and type(node.op) in binary_operators:
            value = binary_operators[type(node.op)](
                evaluate(node.left, depth + 1),
                evaluate(node.right, depth + 1),
            )
        elif isinstance(node, ast.UnaryOp) and type(node.op) in unary_operators:
            value = unary_operators[type(node.op)](
                evaluate(node.operand, depth + 1)
            )
        else:
            raise ValueError("Unsupported calculation.")

        if not math.isfinite(value) or abs(value) > 1_000_000_000:
            raise ValueError("Intermediate result is out of range.")

        return value

    try:
        tree = ast.parse(source, mode="exec")

        if sum(1 for _ in ast.walk(tree)) > 100:
            raise ValueError("Calculation is too complex.")

        if len(tree.body) != 1:
            raise ValueError("Expected one airflow assignment.")

        assignment = tree.body[0]

        if (
            not isinstance(assignment, ast.Assign)
            or len(assignment.targets) != 1
            or not isinstance(assignment.targets[0], ast.Name)
            or assignment.targets[0].id != "airflow"
        ):
            raise ValueError("Expected an assignment to airflow.")

        airflow = evaluate(assignment.value)
    except (SyntaxError, ValueError, ArithmeticError, RecursionError):
        return {"ok": False, "error": "Invalid ventilation calculation."}

    if not 0 < airflow <= 100000:
        return {"ok": False, "error": "Calculation must assign valid airflow."}

    return {
        "ok": True,
        "estimate": {
            "room_id": room_id,
            "occupants": occupants,
            "airflow_m3_per_hour": round(airflow, 2),
            "estimated_at": current_time(),
        },
    }


async def index(request: Request):
    return JSONResponse(
        {
            "application": "Community Studio Ventilation Planner",
            "rooms": "/rooms",
            "estimate": "/ventilation/{room_id}/{occupants}",
            "request_format": "PUT UTF-8 Python calculation text",
            "example": "airflow = area * air_changes + occupants * 10",
        }
    )


async def list_rooms(request: Request):
    return JSONResponse(
        {
            "rooms": [
                {"id": room_id, **details}
                for room_id, details in ROOMS.items()
            ]
        }
    )


async def calculate(request: Request):
    data = bytearray()

    async for chunk in request.stream():
        data.extend(chunk)
        if len(data) > 4096:
            return JSONResponse(
                {"ok": False, "error": "Request body is too large."},
                status_code=413,
            )

    try:
        source = data.decode("utf-8")
    except UnicodeDecodeError:
        return JSONResponse(
            {"ok": False, "error": "Calculation must be UTF-8."},
            status_code=400,
        )

    result = await asyncio.to_thread(
        estimate_ventilation,
        request.path_params["room_id"],
        request.path_params["occupants"],
        source,
    )
    return JSONResponse(result, status_code=200 if result["ok"] else 400)


async def health(request: Request):
    return JSONResponse(
        {
            "status": "ok",
            "room_count": len(ROOMS),
            "timestamp": current_time(),
        }
    )


app = Starlette(
    debug=False,
    routes=[
        Route("/", index),
        Route("/rooms", list_rooms),
        Route(
            "/ventilation/{room_id}/{occupants:int}",
            calculate,
            methods=["PUT"],
        ),
        Route("/health", health),
    ],
)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=8800)
