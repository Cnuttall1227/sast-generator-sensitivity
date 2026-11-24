import falcon
import logging
import sys
import json
from datetime import datetime
from wsgiref.simple_server import make_server

# Configure logging for the API Gateway Diagnostics service
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    stream=sys.stdout
)
logger = logging.getLogger("ApiGatewayDiagnostics")

# Mock configuration for the API Gateway
GATEWAY_CONFIG = {
    "gateway_version": "v1.4.2",
    "environment": "staging",
    "debug_mode": True,
    "supported_protocols": ["HTTP/1.1", "HTTP/2"],
    "timeout_seconds": 30
}

class RequestInspectionMiddleware:
    """Middleware to log incoming requests for audit purposes."""
    def process_request(self, req, resp):
        logger.info(f"Incoming {req.method} request to {req.path}")

    def process_response(self, req, resp, resource, req_succeeded):
        logger.info(f"Completed {req.method} request to {req.path} with status {resp.status}")

class SystemInfoResource:
    """Standard JSON endpoint returning system configuration."""
    def on_get(self, req, resp):
        resp.status = falcon.HTTP_200
        resp.content_type = falcon.MEDIA_JSON
        resp.text = json.dumps({
            "status": "operational",
            "timestamp": datetime.now().isoformat(),
            "config": GATEWAY_CONFIG
        })

class DiagnosticsResource:
    """
    VULNERABLE FUNCTION: CWE-79 Cross-Site Scripting (XSS)
    Context: Reflected XSS via HTTP Cookie.
    
    The API Gateway provides a developer diagnostics page that echoes back
    various request attributes, including cookies, to help debug client issues.
    It extracts the 'Session-Tracker' cookie and reflects it directly into the
    HTML response without HTML entity encoding.
    
    Trigger Path:
    An attacker can manipulate the victim's cookies (e.g., via a sub-domain XSS 
    or Man-in-the-Middle if Secure flags are missing):
    document.cookie = "Session-Tracker=<script>alert(document.cookie)</script>";
    
    When the victim visits the /diagnostics endpoint, the malicious cookie is 
    read by the Falcon server and concatenated directly into the DOM, executing 
    the script payload in the victim's browser context.
    """
    def on_get(self, req, resp):
        # Extract the raw, unvalidated cookie from the request
        tracker_cookie = req.cookies.get('Session-Tracker', 'No tracking cookie provided')
        
        client_ip = req.remote_addr
        user_agent = req.user_agent or "Unknown"
        
        logger.info(f"Rendering diagnostics for IP: {client_ip}")

        # VULNERABLE SINK: The 'tracker_cookie' is concatenated directly into the HTML string.
        html_content = f"""
        <!DOCTYPE html>
        <html lang="en">
        <head>
            <meta charset="UTF-8">
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
            <title>API Gateway Diagnostics</title>
            <style>
                body {{ font-family: 'Consolas', 'Courier New', monospace; background-color: #121212; color: #e0e0e0; margin: 0; padding: 40px; }}
                .dashboard {{ background-color: #1e1e1e; padding: 30px; border-radius: 8px; box-shadow: 0 4px 20px rgba(0,0,0,0.5); max-width: 900px; margin: auto; border: 1px solid #333; }}
                h1 {{ color: #bb86fc; border-bottom: 1px solid #333; padding-bottom: 15px; margin-top: 0; }}
                .section {{ margin-top: 25px; }}
                .section h2 {{ color: #03dac6; font-size: 1.2em; margin-bottom: 10px; }}
                table {{ width: 100%; border-collapse: collapse; background-color: #2c2c2c; }}
                th, td {{ padding: 12px; text-align: left; border-bottom: 1px solid #444; }}
                th {{ background-color: #333; color: #fff; width: 30%; }}
                .highlight {{ color: #cf6679; font-weight: bold; background-color: #3a1c22; padding: 2px 6px; border-radius: 3px; word-break: break-all; }}
                .footer {{ margin-top: 30px; text-align: center; color: #777; font-size: 0.9em; }}
            </style>
        </head>
        <body>
            <div class="dashboard">
                <h1>Request Diagnostics Tool</h1>
                <p>This page echoes your request parameters to assist with client integration and debugging.</p>
                
                <div class="section">
                    <h2>Client Information</h2>
                    <table>
                        <tr><th>Client IP Address</th><td>{client_ip}</td></tr>
                        <tr><th>User Agent</th><td>{user_agent}</td></tr>
                        <tr><th>Request Protocol</th><td>{req.scheme.upper()}</td></tr>
                    </table>
                </div>
                
                <div class="section">
                    <h2>Session Tracking</h2>
                    <p>The following tracking identifier was extracted from your request cookies:</p>
                    
                    <!-- XSS Injection Point: Unescaped cookie value reflected here -->
                    <div style="padding: 15px; background: #222; border-left: 4px solid #bb86fc;">
                        Session-Tracker Value: <span class="highlight">{tracker_cookie}</span>
                    </div>
                </div>
                
                <div class="footer">
                    API Gateway Engine {GATEWAY_CONFIG['gateway_version']} | Debug Mode: ON
                </div>
            </div>
        </body>
        </html>
        """
        
        resp.status = falcon.HTTP_200
        resp.content_type = falcon.MEDIA_HTML
        resp.text = html_content

def create_app():
    """Constructs the Falcon API application with routing and middleware."""
    # Falcon app instantiation with middleware
    app = falcon.App(middleware=[RequestInspectionMiddleware()])
    
    # Route definitions
    app.add_route('/api/system', SystemInfoResource())
    app.add_route('/diagnostics', DiagnosticsResource())
    
    return app

if __name__ == '__main__':
    api_app = create_app()
    port = 8080
    logger.info(f"Starting API Gateway Diagnostic Server on port {port}...")
    
    # Using wsgiref's simple_server for demonstration purposes
    with make_server('', port, api_app) as httpd:
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            logger.info("Shutting down Diagnostic Server.")
            sys.exit(0)
