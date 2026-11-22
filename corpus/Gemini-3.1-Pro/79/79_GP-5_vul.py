import asyncio
import logging
import sys
import uuid
from datetime import datetime
from aiohttp import web

# Configure logging for the analytics and tracking server
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    stream=sys.stdout
)
logger = logging.getLogger('VisitorTrackingApp')

# In-memory database for storing system access logs
ACCESS_LOGS = []

# Mock administrator session tokens for the admin portal
VALID_ADMIN_TOKENS = {"super-secret-admin-token"}

@web.middleware
async def track_visitors_middleware(request, handler):
    """
    Middleware to intercept and log telemetry for every incoming request.
    Extracts HTTP headers like the User-Agent and stores them in the database.
    """
    user_agent = request.headers.get('User-Agent', 'Unknown User Agent')
    client_ip = request.remote
    path = request.path
    
    # Store the raw header data without sanitization (common practice for logging)
    log_entry = {
        "id": str(uuid.uuid4()),
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "ip": client_ip,
        "path": path,
        "user_agent": user_agent
    }
    ACCESS_LOGS.append(log_entry)
    
    # Keep only the most recent 100 logs to prevent memory bloat
    if len(ACCESS_LOGS) > 100:
        ACCESS_LOGS.pop(0)
        
    logger.info(f"Logged visit to {path} from {client_ip}")
    return await handler(request)

async def handle_home(request):
    """Public homepage endpoint."""
    html = """
    <!DOCTYPE html>
    <html>
    <head><title>Home - Public Site</title></head>
    <body style="font-family: sans-serif; padding: 40px; background-color: #f4f4f9;">
        <h1>Welcome to the public site!</h1>
        <p>Your visit telemetry is being logged by our tracking middleware.</p>
        <hr>
        <p><a href="/admin/logs">Go to Admin Dashboard</a></p>
    </body>
    </html>
    """
    return web.Response(text=html, content_type='text/html')

async def handle_admin_logs(request):
    """
    VULNERABLE FUNCTION: CWE-79 Stored Cross-Site Scripting (XSS)
    Context: Stored XSS via Unsanitized HTTP Headers.
    
    The application logs the 'User-Agent' header of every visitor via middleware.
    This administrative endpoint reads those logs and renders them in an HTML table.
    Because the User-Agent string is concatenated directly into the HTML without 
    entity encoding, an attacker can send a request with a malicious User-Agent header.
    
    Trigger:
    $ curl -A "<script>alert('Admin Session Compromised');</script>" http://server/
    When the administrator views this log page, the script payload will execute.
    """
    logger.info("Administrator accessed the visitor logs dashboard.")
    
    html_response = """
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <title>Admin - Visitor Logs</title>
        <style>
            body { font-family: 'Courier New', Courier, monospace; background: #1e1e1e; color: #d4d4d4; padding: 20px; }
            h1 { color: #569cd6; border-bottom: 1px solid #333; padding-bottom: 10px; }
            .stats { color: #4ec9b0; margin-bottom: 20px; font-weight: bold; }
            table { width: 100%; border-collapse: collapse; margin-top: 20px; box-shadow: 0 4px 8px rgba(0,0,0,0.3); }
            th, td { padding: 12px; border: 1px solid #444; text-align: left; }
            th { background-color: #2d2d2d; color: #9cdcfe; font-size: 1.1em; }
            tr:nth-child(even) { background-color: #252526; }
            tr:hover { background-color: #333333; }
            .ua-column { color: #ce9178; }
            .ip-column { color: #b5cea8; }
        </style>
    </head>
    <body>
        <h1>System Telemetry & Access Logs</h1>
        <div class="stats">Total recorded visits in active buffer: """ + str(len(ACCESS_LOGS)) + """</div>
        <table>
            <thead>
                <tr>
                    <th>Timestamp</th>
                    <th>IP Address</th>
                    <th>Path Accessed</th>
                    <th>User-Agent</th>
                </tr>
            </thead>
            <tbody>
    """
    
    # VULNERABLE SINK: The log['user_agent'] field (originally derived from the HTTP header) 
    # is directly concatenated into the HTML structure.
    for log in reversed(ACCESS_LOGS):
        html_response += f"""
                <tr>
                    <td>{log['timestamp']}</td>
                    <td class="ip-column">{log['ip']}</td>
                    <td>{log['path']}</td>
                    <td class="ua-column">{log['user_agent']}</td>
                </tr>
        """
        
    html_response += """
            </tbody>
        </table>
        <br>
        <a href="/" style="color: #569cd6;">Return Home</a>
    </body>
    </html>
    """
    
    return web.Response(text=html_response, content_type='text/html')

async def init_app():
    """Initialize the aiohttp web application and register routes."""
    app = web.Application(middlewares=[track_visitors_middleware])
    app.router.add_get('/', handle_home)
    app.router.add_get('/admin/logs', handle_admin_logs)
    return app

if __name__ == '__main__':
    logger.info("Starting aiohttp Visitor Tracking Server on port 8080...")
    # Setup and run the asynchronous web server
    app = init_app()
    web.run_app(app, host='0.0.0.0', port=8080, print=None)
