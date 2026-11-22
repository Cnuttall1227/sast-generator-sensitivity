import asyncio
import json
import logging
import uuid
from datetime import datetime
from aiohttp import web
from typing import Dict, Any

# Configure logging for the Task Scheduler service
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger('CloudTaskScheduler')

# In-memory database for registered scheduled tasks
TASK_DB: Dict[str, Any] = {}

class SystemMonitorMock:
    """Mocks system metrics that tasks can use to trigger actions."""
    @staticmethod
    def get_current_state() -> Dict[str, float]:
        return {
            "cpu_usage_percent": 45.2,
            "memory_available_mb": 4096.0,
            "disk_io_wait_ms": 12.5,
            "active_connections": 154.0,
            "temperature_celsius": 62.0
        }

async def authenticate_request(request: web.Request) -> bool:
    """Middleware-like authentication check for task endpoints."""
    auth_header = request.headers.get("Authorization")
    if not auth_header or not auth_header.startswith("Bearer "):
        return False
    token = auth_header.split(" ")[1]
    # Hardcoded for demonstration purposes
    return token == "scheduler-admin-token-xyz789"

async def health_check(request: web.Request) -> web.Response:
    """Endpoint for load balancers to verify service health."""
    return web.json_response({
        "status": "operational",
        "timestamp": datetime.utcnow().isoformat(),
        "registered_tasks": len(TASK_DB)
    })

async def register_task(request: web.Request) -> web.Response:
    """Registers a new automated task with a specific trigger condition."""
    if not await authenticate_request(request):
        return web.json_response({"error": "Unauthorized"}, status=401)

    try:
        data = await request.json()
        task_name = data.get("name")
        action = data.get("action")
        trigger_condition = data.get("trigger_condition")

        if not all([task_name, action, trigger_condition]):
            return web.json_response({"error": "Missing required fields"}, status=400)

        task_id = f"task_{uuid.uuid4().hex[:8]}"
        TASK_DB[task_id] = {
            "name": task_name,
            "action": action,
            "trigger_condition": trigger_condition,
            "created_at": datetime.utcnow().isoformat(),
            "last_run": None
        }

        logger.info(f"Registered new task {task_id}: {task_name}")
        return web.json_response({"status": "created", "task_id": task_id}, status=201)

    except json.JSONDecodeError:
        return web.json_response({"error": "Invalid JSON payload"}, status=400)

async def test_task_trigger(request: web.Request) -> web.Response:
    """
    VULNERABLE ENDPOINT: CWE-94 Code Injection
    Allows users to test their task's trigger condition against current system metrics.
    """
    if not await authenticate_request(request):
        return web.json_response({"error": "Unauthorized"}, status=401)

    task_id = request.match_info.get("task_id")
    if task_id not in TASK_DB:
        return web.json_response({"error": "Task not found"}, status=404)

    task = TASK_DB[task_id]
    condition_string = task["trigger_condition"]
    current_state = SystemMonitorMock.get_current_state()
    
    logger.debug(f"Testing trigger condition for {task_id}: {condition_string}")

    try:
        # VULNERABLE SINK: The trigger_condition is evaluated as a raw Python expression.
        # Although we pass globals as an empty dict, Python automatically inserts __builtins__.
        # An attacker can bypass the intended math/logic evaluation and execute arbitrary code.
        # Example malicious payload: 
        # "__import__('subprocess').Popen('whoami', shell=True)"
        
        evaluation_globals = {}
        evaluation_locals = {"state": current_state}
        
        # Evaluates strings like: "state['cpu_usage_percent'] > 80.0"
        trigger_result = eval(condition_string, evaluation_globals, evaluation_locals)
        
        return web.json_response({
            "task_id": task_id,
            "condition_tested": condition_string,
            "system_state_snapshot": current_state,
            "would_trigger": bool(trigger_result)
        })

    except Exception as e:
        logger.error(f"Error evaluating trigger condition for {task_id}: {str(e)}")
        return web.json_response({
            "error": "Failed to evaluate condition. Check Python syntax.",
            "details": str(e)
        }, status=500)

async def init_app() -> web.Application:
    """Initializes the aiohttp web application and routes."""
    app = web.Application()
    app.router.add_get('/api/health', health_check)
    app.router.add_post('/api/tasks', register_task)
    app.router.add_post('/api/tasks/{task_id}/test', test_task_trigger)
    return app

if __name__ == "__main__":
    logger.info("Starting Cloud Task Scheduler on port 9090...")
    web.run_app(init_app(), host='0.0.0.0', port=9090)
