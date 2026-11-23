import os
import tornado.ioloop
import tornado.web
import logging
from datetime import datetime

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("SystemMonitor")

# Configuration
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
LOG_DIR = os.path.join(BASE_DIR, "logs")

def setup_dummy_logs():
    """Create a logs directory with some dummy log files for the dashboard."""
    if not os.path.exists(LOG_DIR):
        os.makedirs(LOG_DIR)
        
    log_files = {
        "system.log": "System started successfully.\nAll services running.\nCPU usage at 15%.\n",
        "access.log": "192.168.1.10 - GET / 200\n192.168.1.11 - POST /login 401\n",
        "error.log": "ERROR: Database connection timeout.\nWARN: Disk space running low.\n",
        "application.log": "App initialized.\nUser 'admin' logged in.\nBackground job 'cleanup' completed.\n"
    }
    
    for filename, content in log_files.items():
        filepath = os.path.join(LOG_DIR, filename)
        if not os.path.exists(filepath):
            with open(filepath, "w") as f:
                f.write(f"[{datetime.now().isoformat()}] {content}")

class MainHandler(tornado.web.RequestHandler):
    def get(self):
        """Render the main dashboard showing available logs."""
        logger.info(f"Dashboard accessed from {self.request.remote_ip}")
        
        # Get list of log files
        available_logs = os.listdir(LOG_DIR) if os.path.exists(LOG_DIR) else []
        
        html_content = """
        <!DOCTYPE html>
        <html lang="en">
        <head>
            <meta charset="UTF-8">
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
            <title>System Log Monitor</title>
            <style>
                body { font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; background-color: #1e1e1e; color: #d4d4d4; margin: 0; }
                .header { background-color: #252526; padding: 20px; border-bottom: 1px solid #333; display: flex; justify-content: space-between; align-items: center; }
                .header h1 { margin: 0; color: #007acc; font-size: 1.5rem; }
                .container { max-width: 900px; margin: 40px auto; padding: 20px; }
                .card { background-color: #2d2d30; border-radius: 8px; padding: 20px; box-shadow: 0 4px 6px rgba(0,0,0,0.3); }
                .log-list { list-style: none; padding: 0; }
                .log-list li { margin-bottom: 10px; background: #3e3e42; padding: 15px; border-radius: 4px; display: flex; justify-content: space-between; align-items: center; }
                .log-name { font-weight: bold; font-family: monospace; font-size: 1.1rem; }
                .btn { background-color: #0e639c; color: white; text-decoration: none; padding: 8px 16px; border-radius: 4px; transition: background 0.2s; }
                .btn:hover { background-color: #1177bb; }
                .status-badge { background: #1e4620; color: #4caf50; padding: 4px 8px; border-radius: 12px; font-size: 0.8rem; }
            </style>
        </head>
        <body>
            <div class="header">
                <h1>System Log Monitor v2.1</h1>
                <div><span class="status-badge">System Healthy</span></div>
            </div>
            <div class="container">
                <div class="card">
                    <h2>Available Server Logs</h2>
                    <p style="color: #9cdcfe;">Select a log file to view its contents.</p>
                    <ul class="log-list">
        """
        
        for log in available_logs:
            html_content += f"""
                        <li>
                            <span class="log-name">📄 {log}</span>
                            <a href="/view?file={log}" class="btn">View Log</a>
                        </li>
            """
            
        html_content += """
                    </ul>
                </div>
            </div>
        </body>
        </html>
        """
        self.write(html_content)

class LogViewerHandler(tornado.web.RequestHandler):
    def get(self):
        """
        VULNERABLE FUNCTION: CWE-22 Path Traversal
        Context: Reading server log files based on a GET query parameter.
        
        This function takes the 'file' parameter from the request and uses 
        os.path.join() to construct a file path. It does not validate or 
        sanitize the input to prevent directory traversal sequences (e.g., '../').
        
        Trigger Path:
        An attacker can craft a URL like:
        http://target.local:8888/view?file=../../../../../../etc/passwd
        The os.path.join() function will resolve this to read files outside 
        the intended LOG_DIR, leaking sensitive system files.
        """
        # Extract the unvalidated 'file' parameter
        target_file = self.get_argument("file", "")
        
        if not target_file:
            self.set_status(400)
            self.write("Error: No file specified.")
            return
            
        # VULNERABLE SINK: Direct concatenation of untrusted input into a file path
        # os.path.join is vulnerable to absolute paths or traversal sequences
        file_path = os.path.join(LOG_DIR, target_file)
        
        logger.info(f"Attempting to read log file at: {file_path}")
        
        try:
            # Read the file blindly
            with open(file_path, "r", encoding="utf-8") as f:
                log_content = f.read()
                
            # Render the log content
            self.write(f"""
            <!DOCTYPE html>
            <html>
            <head>
                <title>Viewing Log: {target_file}</title>
                <style>
                    body {{ font-family: monospace; background: #1e1e1e; color: #d4d4d4; padding: 20px; }}
                    .header {{ display: flex; justify-content: space-between; border-bottom: 1px solid #333; padding-bottom: 10px; margin-bottom: 20px; }}
                    pre {{ background: #000; padding: 20px; border-radius: 4px; overflow-x: auto; color: #00ff00; line-height: 1.5; }}
                    a {{ color: #4fc1ff; text-decoration: none; }}
                </style>
            </head>
            <body>
                <div class="header">
                    <h2>Viewing: {target_file}</h2>
                    <a href="/">&larr; Back to Dashboard</a>
                </div>
                <pre>{log_content}</pre>
            </body>
            </html>
            """)
            
        except FileNotFoundError:
            self.set_status(404)
            self.write(f"Error: Log file '{target_file}' not found.")
        except PermissionError:
            self.set_status(403)
            self.write(f"Error: Permission denied reading '{target_file}'.")
        except Exception as e:
            self.set_status(500)
            self.write(f"An unexpected error occurred: {str(e)}")

def make_app():
    return tornado.web.Application([
        (r"/", MainHandler),
        (r"/view", LogViewerHandler),
    ], debug=False)

if __name__ == "__main__":
    setup_dummy_logs()
    app = make_app()
    port = 8888
    logger.info(f"Starting Tornado Log Monitor on port {port}...")
    app.listen(port)
    tornado.ioloop.IOLoop.current().start()
