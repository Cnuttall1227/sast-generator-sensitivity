import json
import logging
import asyncio
from datetime import datetime
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse
import uvicorn

# Configure logging for the Diagnostic Service
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - NetDiagApp - %(levelname)s - %(message)s'
)
logger = logging.getLogger("NetworkDiagnostics")

app = FastAPI(title="Network Diagnostic WebSocket API")

# In-memory store for diagnostic history
diagnostic_history = []

def record_history(client_ip: str, target: str, action: str, status: str):
    """Records the diagnostic request history."""
    entry = {
        "timestamp": datetime.now().isoformat(),
        "client_ip": client_ip,
        "target": target,
        "action": action,
        "status": status
    }
    diagnostic_history.append(entry)
    # Keep only the last 100 entries to prevent memory bloat
    if len(diagnostic_history) > 100:
        diagnostic_history.pop(0)

async def execute_diagnostic_command(target: str, action: str, ws: WebSocket):
    """
    VULNERABLE FUNCTION: CWE-77 Command Injection
    Trigger Path: WebSocket JSON Message ('target' field)
    """
    logger.info(f"Initiating {action} against target: {target}")

    # Vulnerability: Direct string interpolation of the WebSocket input into a shell command.
    # The 'target' is extracted directly from the parsed JSON without sanitization.
    if action == "ping":
        # Using a timeout via the command line utility itself
        command = f"ping -c 3 -W 2 {target}"
    elif action == "traceroute":
        command = f"traceroute -m 15 {target}"
    else:
        await ws.send_text(json.dumps({"error": "Unsupported action"}))
        return False

    try:
        logger.debug(f"Executing diagnostic command: {command}")

        # asyncio.create_subprocess_shell evaluates the command string via the system shell.
        # An attacker sending a crafted JSON message via the WebSocket can append shell
        # metacharacters (like ';', '|', or '&&') to break out of the intended command context.
        process = await asyncio.create_subprocess_shell(
            command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )

        # Stream the output back to the WebSocket client in real-time
        while True:
            line = await process.stdout.readline()
            if not line:
                break
            await ws.send_text(json.dumps({"type": "stdout", "data": line.decode('utf-8').strip()}))

        stderr_data = await process.stderr.read()
        if stderr_data:
            await ws.send_text(json.dumps({"type": "stderr", "data": stderr_data.decode('utf-8').strip()}))

        await process.wait()

        if process.returncode == 0:
            logger.info(f"Diagnostic command completed successfully for {target}")
            return True
        else:
            logger.warning(f"Diagnostic command failed with code {process.returncode}")
            return False

    except Exception as e:
        logger.error(f"Internal error executing command: {e}")
        await ws.send_text(json.dumps({"type": "error", "data": f"Execution error: {str(e)}"}))
        return False

@app.websocket("/ws/diagnostics")
async def websocket_endpoint(websocket: WebSocket):
    """WebSocket endpoint for real-time network diagnostics."""
    await websocket.accept()
    client_ip = websocket.client.host if websocket.client else "unknown"
    logger.info(f"New WebSocket connection established from {client_ip}")

    try:
        while True:
            data = await websocket.receive_text()
            try:
                payload = json.loads(data)
            except json.JSONDecodeError:
                await websocket.send_text(json.dumps({"error": "Invalid JSON payload"}))
                continue

            target = payload.get("target")
            action = payload.get("action", "ping")

            if not target:
                await websocket.send_text(json.dumps({"error": "Missing 'target' field"}))
                continue

            await websocket.send_text(json.dumps({"type": "info", "data": f"Starting {action} for {target}..."}))

            # Pass the untrusted WebSocket input to the vulnerable function
            success = await execute_diagnostic_command(target, action, websocket)

            status = "SUCCESS" if success else "FAILED"
            record_history(client_ip, target, action, status)

            await websocket.send_text(json.dumps({"type": "info", "data": f"Diagnostic {action} finished."}))

    except WebSocketDisconnect:
        logger.info(f"WebSocket client {client_ip} disconnected.")
    except Exception as e:
        logger.error(f"Unexpected WebSocket error: {e}")

# Serve a simple HTML client to interact with the WebSocket
html_client = """
<!DOCTYPE html>
<html>
    <head>
        <title>Network Diagnostics Console</title>
        <style>
            body { font-family: monospace; background-color: #1e1e1e; color: #00ff00; padding: 20px; }
            input, button, select { padding: 10px; margin-top: 10px; background-color: #333; color: white; border: 1px solid #555; }
            #output { margin-top: 20px; padding: 10px; border: 1px solid #555; min-height: 300px; white-space: pre-wrap; }
            .stderr { color: #ff5555; }
            .info { color: #ffff55; }
        </style>
    </head>
    <body>
        <h2>Live Network Diagnostics Console</h2>
        <p>Enter a target hostname or IP address to run diagnostics.</p>
        <form action="" onsubmit="sendMessage(event)">
            <select id="action">
                <option value="ping">Ping</option>
                <option value="traceroute">Traceroute</option>
            </select>
            <input type="text" id="target" autocomplete="off" placeholder="e.g., 8.8.8.8" size="40"/>
            <button>Execute</button>
        </form>
        <div id="output"></div>
        <script>
            var ws = new WebSocket("ws://" + window.location.host + "/ws/diagnostics");
            var outputDiv = document.getElementById('output');

            ws.onmessage = function(event) {
                var msg = JSON.parse(event.data);
                var span = document.createElement('span');
                if (msg.type === 'stderr' || msg.error) {
                    span.className = 'stderr';
                    span.textContent = (msg.data || msg.error) + "\\n";
                } else if (msg.type === 'info') {
                    span.className = 'info';
                    span.textContent = "--- " + msg.data + " ---\\n";
                } else {
                    span.textContent = msg.data + "\\n";
                }
                outputDiv.appendChild(span);
                window.scrollTo(0, document.body.scrollHeight);
            };

            function sendMessage(event) {
                var target = document.getElementById("target").value;
                var action = document.getElementById("action").value;
                var payload = JSON.stringify({ "target": target, "action": action });
                ws.send(payload);
                event.preventDefault();
            }
        </script>
    </body>
</html>
"""

@app.get("/")
async def get_client():
    """Serves the frontend HTML client."""
    return HTMLResponse(html_client)

@app.get("/api/history")
async def get_history():
    """REST endpoint returning recent diagnostic executions."""
    return {"history": diagnostic_history}

if __name__ == "__main__":
    # Example Malicious WebSocket JSON Payload:
    # {"target": "127.0.0.1; cat /etc/passwd", "action": "ping"}
    
    logger.info("Starting Async Network Diagnostics app on port 8000")
    uvicorn.run(app, host="0.0.0.0", port=8000)
