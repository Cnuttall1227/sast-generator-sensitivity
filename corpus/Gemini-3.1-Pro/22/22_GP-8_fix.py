import os
import json
import logging
import tornado.ioloop
import tornado.web
import tornado.websocket

# Configure logging for the Diagnostics Service
logging.basicConfig(level=logging.INFO, format="%(asctime)s [TORNADO] %(levelname)s: %(message)s")
logger = logging.getLogger("SysDiag")

# Application configuration paths
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
LOGS_DIR = os.path.join(BASE_DIR, "system_logs")

def generate_mock_logs():
    """Create the system_logs directory and populate it with sample application logs."""
    if not os.path.exists(LOGS_DIR):
        os.makedirs(LOGS_DIR)
        
    mock_logs = {
        "server_access.log": "192.168.1.10 - GET / 200\n192.168.1.11 - POST /login 401\n",
        "error_trace.log": "Exception in thread 'main': NullReferenceException at Core.init\n",
        "worker_queue.log": "Job 4912 started.\nJob 4912 completed in 0.4s.\nJob 4913 pending.\n"
    }
    
    for filename, content in mock_logs.items():
        filepath = os.path.join(LOGS_DIR, filename)
        if not os.path.exists(filepath):
            with open(filepath, "w", encoding="utf-8") as f:
                f.write(content)
                
    logger.info(f"Initialized mock system logs at {LOGS_DIR}")

class DashboardHandler(tornado.web.RequestHandler):
    def get(self):
        """Render the main WebSocket-driven diagnostic dashboard."""
        html_content = """
        <!DOCTYPE html>
        <html lang="en">
        <head>
            <meta charset="UTF-8">
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
            <title>Real-time Diagnostic Console</title>
            <style>
                body { font-family: 'Courier New', Courier, monospace; background: #121212; color: #00ff00; margin: 0; padding: 20px; }
                .panel { border: 1px solid #333; padding: 20px; border-radius: 4px; background: #000; box-shadow: 0 0 10px rgba(0,255,0,0.1); }
                h1 { margin-top: 0; border-bottom: 1px solid #333; padding-bottom: 10px; font-size: 1.5rem; }
                .controls { margin-bottom: 20px; display: flex; gap: 15px; align-items: center; }
                select, button { background: #222; color: #00ff00; border: 1px solid #00ff00; padding: 8px 12px; font-family: inherit; cursor: pointer; }
                button:hover { background: #00ff00; color: #000; }
                #log-output { white-space: pre-wrap; word-wrap: break-word; min-height: 300px; color: #a6e22e; }
                .status-indicator { display: inline-block; width: 10px; height: 10px; border-radius: 50%; background: red; margin-right: 8px; }
                .connected { background: #00ff00; }
            </style>
        </head>
        <body>
            <div class="panel">
                <h1><span id="ws-status" class="status-indicator"></span>Real-time Diagnostic Console</h1>
                <div class="controls">
                    <select id="log-selector">
                        <option value="server_access.log">Access Logs</option>
                        <option value="error_trace.log">Error Traces</option>
                        <option value="worker_queue.log">Worker Queues</option>
                    </select>
                    <button onclick="fetchLog()">Stream Log File</button>
                </div>
                <div id="log-output">Connecting to WebSocket telemetry stream...</div>
            </div>

            <script>
                const ws = new WebSocket(`ws://${location.host}/ws/diagnostics`);
                const output = document.getElementById('log-output');
                const status = document.getElementById('ws-status');

                ws.onopen = () => {
                    status.classList.add('connected');
                    output.textContent = 'System ready. Select a log file to stream.';
                };

                ws.onmessage = (event) => {
                    const response = JSON.parse(event.data);
                    if (response.status === 'success') {
                        output.textContent = response.data;
                    } else {
                        output.textContent = `[ERROR] ${response.message}`;
                        output.style.color = '#ff0000';
                    }
                };

                ws.onclose = () => {
                    status.classList.remove('connected');
                    output.textContent = 'Connection to diagnostic server lost.';
                };

                function fetchLog() {
                    if (ws.readyState !== WebSocket.OPEN) return;
                    const logFile = document.getElementById('log-selector').value;
                    output.style.color = '#a6e22e';
                    output.textContent = 'Requesting telemetry...';
                    
                    // Send a JSON command over the WebSocket connection
                    ws.send(JSON.stringify({
                        command: 'read_log',
                        target_file: logFile
                    }));
                }
            </script>
        </body>
        </html>
        """
        self.write(html_content)

# Assuming LOGS_DIR and logger are defined in the broader file scope
# LOGS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "system_logs")
# logger = logging.getLogger("SysDiag")

class DiagnosticSocketHandler(tornado.websocket.WebSocketHandler):
    def check_origin(self, origin):
        return True

    def open(self):
        logger.info("New diagnostic WebSocket connection established.")

    def on_message(self, message):
        """
        FIXED: CWE-22 Path Traversal
        Context: Reading system log files via a Tornado WebSocket JSON payload.
        
        The 'target_file' parameter is now strictly validated to ensure that the 
        resolved absolute path of the requested log file remains inside the 
        intended LOGS_DIR. This neutralizes directory traversal sequences 
        like '../' and absolute path injections.
        """
        try:
            payload = json.loads(message)
        except json.JSONDecodeError:
            self.write_message(json.dumps({"status": "error", "message": "Invalid JSON payload"}))
            return

        command = payload.get("command")
        target_file = payload.get("target_file")

        if command != "read_log" or not target_file:
            self.write_message(json.dumps({"status": "error", "message": "Invalid command or missing target_file"}))
            return

        logger.info(f"WebSocket requesting log file: {target_file}")

        # FIXED SINK: Secure path resolution to prevent CWE-22
        # 1. Get the absolute path of the intended base directory
        abs_base_dir = os.path.abspath(LOGS_DIR)
        
        # 2. Construct the requested path and resolve its absolute path
        file_path = os.path.abspath(os.path.join(abs_base_dir, target_file))
        
        # 3. Verify the resolved path is strictly within the base directory
        # os.path.commonpath prevents partial directory name bypasses
        if os.path.commonpath([abs_base_dir, file_path]) != abs_base_dir:
            logger.warning(f"Path traversal attempt blocked: {target_file}")
            self.write_message(json.dumps({"status": "error", "message": "Forbidden: Invalid log file path."}))
            return

        try:
            # Safely open and read the file at the validated path
            with open(file_path, "r", encoding="utf-8") as f:
                log_data = f.read()

            # Send the sensitive file contents back through the WebSocket
            self.write_message(json.dumps({
                "status": "success",
                "file": target_file,
                "data": log_data
            }))

        except FileNotFoundError:
            logger.error(f"Log file not found: {file_path}")
            self.write_message(json.dumps({"status": "error", "message": "Log file not found."}))
        except PermissionError:
            logger.error(f"Permission denied: {file_path}")
            self.write_message(json.dumps({"status": "error", "message": "Permission denied."}))
        except Exception as e:
            logger.error(f"Unexpected error: {str(e)}")
            self.write_message(json.dumps({"status": "error", "message": "Internal server error."}))

    def on_close(self):
        logger.info("Diagnostic WebSocket connection closed.")

def make_app():
    return tornado.web.Application([
        (r"/", DashboardHandler),
        (r"/ws/diagnostics", DiagnosticSocketHandler),
    ], debug=False)

if __name__ == "__main__":
    generate_mock_logs()
    app = make_app()
    port = 8888
    app.listen(port)
    logger.info(f"Tornado Diagnostic Server running on http://localhost:{port}")
    try:
        tornado.ioloop.IOLoop.current().start()
    except KeyboardInterrupt:
        logger.info("Shutting down diagnostic server...")
        tornado.ioloop.IOLoop.current().stop()
