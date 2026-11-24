import sys
import logging
import json
from twisted.web.server import Site, Request
from twisted.web.resource import Resource
from twisted.internet import reactor, endpoints
from datetime import datetime

# Configure logging for the Feature Flag Service
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    stream=sys.stdout
)
logger = logging.getLogger("FeatureFlagService")

# In-memory mock database for feature flags
FEATURE_FLAGS = {
    "new_checkout_flow": {"status": "enabled", "owner": "ecomm-team"},
    "beta_dashboard": {"status": "disabled", "owner": "frontend-core"},
    "legacy_api_deprecation": {"status": "enabled", "owner": "backend-api"}
}

class FeatureFlagDashboard(Resource):
    """Main dashboard for viewing current feature flag statuses."""
    isLeaf = True

    def render_GET(self, request: Request):
        client_ip = request.getClientAddress().host
        logger.info(f"Dashboard accessed by {client_ip}")
        request.setHeader(b"content-type", b"text/html; charset=utf-8")
        
        html = """
        <!DOCTYPE html>
        <html lang="en">
        <head>
            <meta charset="UTF-8">
            <title>Feature Flag Management</title>
            <style>
                body { font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; padding: 30px; background: #2c3e50; color: #ecf0f1; }
                .container { max-width: 800px; margin: 0 auto; background: #34495e; padding: 30px; border-radius: 8px; box-shadow: 0 5px 15px rgba(0,0,0,0.3); }
                h1 { border-bottom: 2px solid #e74c3c; padding-bottom: 10px; margin-top: 0; }
                table { width: 100%; border-collapse: collapse; margin-top: 20px; }
                th, td { padding: 12px; text-align: left; border-bottom: 1px solid #7f8c8d; }
                th { background-color: #2c3e50; color: #ecf0f1; }
                .enabled { color: #2ecc71; font-weight: bold; }
                .disabled { color: #e74c3c; font-weight: bold; }
                .footer { margin-top: 30px; font-size: 0.85em; color: #bdc3c7; }
            </style>
        </head>
        <body>
            <div class="container">
                <h1>Feature Flag Control Center</h1>
                <p>Monitor and toggle active configuration states across microservices.</p>
                <table>
                    <tr><th>Flag Name</th><th>Status</th><th>Owner</th></tr>
        """
        
        for name, details in FEATURE_FLAGS.items():
            status_class = details['status']
            html += f"<tr><td>{name}</td><td class='{status_class}'>{details['status'].upper()}</td><td>{details['owner']}</td></tr>"
            
        html += f"""
                </table>
                <div class="footer">
                    System time: {datetime.now().isoformat()} | Engine: Twisted Web
                </div>
            </div>
        </body>
        </html>
        """
        return html.encode('utf-8')


class FeatureFlagAPI(Resource):
    """JSON API endpoint for programmatic flag checking."""
    isLeaf = True
    
    def render_GET(self, request: Request):
        request.setHeader(b"content-type", b"application/json")
        return json.dumps({
            "flags": FEATURE_FLAGS, 
            "count": len(FEATURE_FLAGS),
            "timestamp": datetime.now().isoformat()
        }).encode('utf-8')


import html

class NotFoundErrorHandler(Resource):
    """Custom 404 handler that captures errors and provides navigation."""
    isLeaf = True

    def render_GET(self, request: Request):
        """
        FIXED: CWE-79 Cross-Site Scripting (XSS)
        Context: Reflected XSS via HTTP Referer Header in Twisted Web.
        
        The extracted 'Referer' header is now properly HTML-escaped before being 
        concatenated into the HTML response, neutralizing any malicious script payloads.
        """
        raw_referer_bytes = request.getHeader(b"referer")
        
        if raw_referer_bytes:
            referer = raw_referer_bytes.decode('utf-8', errors='ignore')
        else:
            referer = "/"

        logger.warning(f"404 Error triggered for path: {request.path}. Referer: {referer}")

        request.setResponseCode(404)
        request.setHeader(b"content-type", b"text/html; charset=utf-8")

        # FIXED SINK: Escape the untrusted referer value to prevent HTML/JS injection.
        # This safely converts characters like '<', '>', '&', '"', and "'" to their 
        # respective HTML entities.
        safe_referer = html.escape(referer)

        html_content = f"""
        <!DOCTYPE html>
        <html lang="en">
        <head>
            <meta charset="UTF-8">
            <title>Page Not Found</title>
            <style>
                body {{ font-family: 'Segoe UI', sans-serif; background-color: #fce4e4; color: #333; padding: 50px; text-align: center; }}
                .error-box {{ background-color: #fff; padding: 40px; border-radius: 10px; box-shadow: 0px 4px 15px rgba(0,0,0,0.1); display: inline-block; }}
                h1 {{ color: #c0392b; margin-top: 0; }}
                .back-link {{ display: inline-block; margin-top: 20px; padding: 10px 20px; background-color: #3498db; color: #fff; text-decoration: none; border-radius: 5px; font-weight: bold; }}
                .referer {{ font-style: italic; color: #7f8c8d; margin-top: 25px; word-break: break-all; max-width: 500px; margin-left: auto; margin-right: auto; padding: 15px; background: #f9f9f9; border: 1px solid #eee; }}
            </style>
        </head>
        <body>
            <div class="error-box">
                <h1>404 - Resource Not Found</h1>
                <p>The feature flag route or API endpoint you are looking for does not exist.</p>
                <p>It may have been moved, or you might not have the correct permissions.</p>
                
                <!-- FIXED: Safely escaped attribute context -->
                <a href="{safe_referer}" class="back-link">Return to Previous Page</a>
                
                <div class="referer">
                    Attempted to navigate from: <br><br>
                    <!-- FIXED: Safely escaped HTML body context -->
                    <strong>{safe_referer}</strong>
                </div>
            </div>
        </body>
        </html>
        """
        
        return html_content.encode('utf-8')

class RootRoutingResource(Resource):
    """Main routing node mapping URI segments to specific resources."""
    isLeaf = False
    
    def getChild(self, path, request):
        if path == b'':
            return FeatureFlagDashboard()
        elif path == b'api':
            return FeatureFlagAPI()
        else:
            return NotFoundErrorHandler()

def start_server():
    """Initializes and binds the Twisted Web application server."""
    port = 8080
    root = RootRoutingResource()
    factory = Site(root)
    
    endpoint = endpoints.TCP4ServerEndpoint(reactor, port)
    endpoint.listen(factory)
    
    logger.info(f"Starting Twisted Feature Flag Service on port {port}...")
    reactor.run()

if __name__ == '__main__':
    try:
        start_server()
    except KeyboardInterrupt:
        logger.info("Service interrupted by user. Shutting down reactor.")
        sys.exit(0)
