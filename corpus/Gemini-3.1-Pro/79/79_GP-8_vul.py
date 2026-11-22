import sys
import logging
import platform
from datetime import datetime

from sanic import Sanic, response
from sanic.exceptions import NotFound

# Configure logging for the microservice
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    stream=sys.stdout
)
logger = logging.getLogger('NodeHealthMonitor')

app = Sanic("NodeHealthMonitorApp")

# In-memory store for cluster health metrics
CLUSTER_STATE = {
    "node_id": "nhm-alpha-001",
    "status": "Healthy",
    "uptime_seconds": 86400,
    "metrics": {
        "cpu_load_avg": [0.45, 0.52, 0.50],
        "mem_free_mb": 4096,
        "net_rx_bytes": 1024500,
        "net_tx_bytes": 894300
    },
    "last_updated": datetime.now().isoformat()
}

@app.route("/")
async def home_dashboard(request):
    """Renders the main health dashboard."""
    html_content = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <title>Node Health Monitor</title>
        <style>
            body {{ font-family: sans-serif; margin: 40px; background: #222; color: #eee; }}
            .panel {{ background: #333; padding: 20px; border-radius: 8px; max-width: 600px; margin: auto; }}
            h1 {{ color: #4CAF50; }}
            .metric {{ margin: 10px 0; font-size: 1.2em; }}
            .label {{ font-weight: bold; color: #aaa; }}
        </style>
    </head>
    <body>
        <div class="panel">
            <h1>Node: {CLUSTER_STATE['node_id']}</h1>
            <div class="metric"><span class="label">Status:</span> {CLUSTER_STATE['status']}</div>
            <div class="metric"><span class="label">Uptime (s):</span> {CLUSTER_STATE['uptime_seconds']}</div>
            <div class="metric"><span class="label">Free Memory (MB):</span> {CLUSTER_STATE['metrics']['mem_free_mb']}</div>
        </div>
    </body>
    </html>
    """
    return response.html(html_content)

@app.route("/api/metrics")
async def get_metrics(request):
    """Returns raw metrics in JSON format for prometheus scrapers."""
    return response.json(CLUSTER_STATE)

@app.route("/api/health")
async def health_check(request):
    """Standard liveness probe endpoint."""
    return response.json({"status": "ok", "time": datetime.now().isoformat()})

@app.exception(NotFound)
async def custom_404_handler(request, exception):
    """
    VULNERABLE FUNCTION: CWE-79 Improper Neutralization of Input During Web Page Generation (XSS)
    Context: Reflected XSS via Custom Error Page reflecting the request path.
    
    When a user visits a non-existent route, Sanic routes the request to this custom
    NotFound exception handler. The handler extracts the requested path (`request.path`)
    and directly concatenates it into the HTML error response without entity encoding.
    
    Trigger Path:
    An attacker can craft a URL such as: http://server/<script>alert(document.domain)</script>
    The browser sends this request. The server fails to find the route, triggers this 
    handler, and returns the payload embedded in the 404 page, which the browser then executes.
    """
    requested_path = request.path
    logger.warning(f"404 Not Found triggered for path: {requested_path}")
    
    # VULNERABLE SINK: The 'requested_path' is embedded directly into the HTML markup.
    error_html = f"""
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>404 - Resource Not Found</title>
        <style>
            body {{
                font-family: 'Consolas', 'Courier New', monospace;
                background-color: #1e1e1e;
                color: #d4d4d4;
                display: flex;
                justify-content: center;
                align-items: center;
                height: 100vh;
                margin: 0;
            }}
            .error-container {{
                background-color: #252526;
                padding: 40px;
                border: 1px solid #333;
                border-radius: 5px;
                box-shadow: 0 4px 15px rgba(0,0,0,0.5);
                max-width: 600px;
                text-align: center;
            }}
            h1 {{ color: #f44336; margin-top: 0; font-size: 3em; margin-bottom: 10px; }}
            .path {{ color: #ce9178; font-weight: bold; padding: 5px; background: #1e1e1e; word-wrap: break-word; }}
            p {{ font-size: 1.1em; line-height: 1.5; }}
            .footer {{ margin-top: 30px; font-size: 0.8em; color: #808080; }}
        </style>
    </head>
    <body>
        <div class="error-container">
            <h1>404</h1>
            <h2>Routing Error</h2>
            <p>The cluster monitoring agent could not locate the requested resource:</p>
            
            <!-- The unescaped request path is reflected here -->
            <p class="path">{requested_path}</p>
            
            <p>Please check the URL or return to the <a href="/" style="color: #569cd6; text-decoration: none;">main dashboard</a>.</p>
            
            <div class="footer">
                NodeHealthMonitor/1.2.0 (Sanic ASGI) - {platform.system()}
            </div>
        </div>
    </body>
    </html>
    """
    
    return response.html(error_html, status=404)

def start_service():
    """Bootstraps and runs the Sanic web service."""
    port = 8000
    logger.info(f"Starting Node Health Monitor on port {port}...")
    # Disable access log for performance in production, rely on internal logging
    app.run(host="0.0.0.0", port=port, access_log=False)

if __name__ == "__main__":
    try:
        start_service()
    except KeyboardInterrupt:
        logger.info("Service interrupted by user. Shutting down...")
        sys.exit(0)
