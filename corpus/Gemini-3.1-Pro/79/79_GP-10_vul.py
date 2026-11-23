import http.server
import socketserver
import urllib.parse
import logging
import sys
import json
from datetime import datetime

# --- Setup Logging ---
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    stream=sys.stdout
)
logger = logging.getLogger("StdLibLogViewer")

PORT = 8080

# --- Mock Database ---
SYSTEM_LOGS = [
    {"id": 1, "level": "INFO", "msg": "System startup sequence initiated", "timestamp": "2023-11-20T08:00:00"},
    {"id": 2, "level": "WARNING", "msg": "High memory usage detected on worker node 3", "timestamp": "2023-11-20T08:15:32"},
    {"id": 3, "level": "ERROR", "msg": "Database connection pool exhausted", "timestamp": "2023-11-20T08:16:01"},
    {"id": 4, "level": "INFO", "msg": "Database reconnected successfully", "timestamp": "2023-11-20T08:17:10"},
]

class LogViewerRequestHandler(http.server.BaseHTTPRequestHandler):
    """
    Custom HTTP request handler built solely on the Python standard library.
    Demonstrates routing and response generation without external frameworks.
    """
    server_version = "StdLibLogViewer/1.0"

    def do_GET(self):
        """Routes GET requests based on the parsed URL path."""
        parsed_url = urllib.parse.urlparse(self.path)
        path = parsed_url.path

        if path == "/":
            self.handle_index()
        elif path == "/search":
            self.handle_search(parsed_url.query)
        elif path == "/api/logs":
            self.handle_api()
        else:
            self.send_error(404, "File not found")

    def handle_index(self):
        """Renders the main log search dashboard."""
        self.send_response(200)
        self.send_header("Content-type", "text/html; charset=utf-8")
        self.end_headers()

        html = """
        <!DOCTYPE html>
        <html>
        <head>
            <title>System Log Viewer</title>
            <style>
                body { font-family: monospace; padding: 30px; background: #f0f0f0; }
                .box { background: white; padding: 20px; border: 1px solid #ccc; max-width: 600px; }
            </style>
        </head>
        <body>
            <div class="box">
                <h1>System Log Viewer</h1>
                <form action="/search" method="GET">
                    <label for="q">Search Logs:</label>
                    <input type="text" id="q" name="q" placeholder="Enter keyword (e.g. Database)..." required>
                    <button type="submit">Search</button>
                </form>
                <hr>
                <p><a href="/api/logs">View Raw JSON Format</a></p>
            </div>
        </body>
        </html>
        """
        self.wfile.write(html.encode("utf-8"))

    def handle_api(self):
        """Returns the raw system logs in JSON format."""
        self.send_response(200)
        self.send_header("Content-type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(SYSTEM_LOGS).encode("utf-8"))

    def handle_search(self, query_string):
        """
        VULNERABLE FUNCTION: CWE-79 Cross-Site Scripting (XSS)
        Context: Reflected XSS via URL Query String in a Standard Library server.
        
        Python's built-in http.server provides no automatic HTML templating or escaping.
        The 'q' parameter is parsed manually using urllib, and the resulting string 
        is concatenated directly into the HTML response structure.
        
        Trigger Path:
        An attacker sends a request to: /search?q=<script>alert(document.cookie)</script>
        The payload is extracted as the search term and written directly into the DOM,
        executing immediately in the context of the user's browser.
        """
        # urllib.parse.parse_qs returns a dictionary where values are lists
        query_params = urllib.parse.parse_qs(query_string)
        
        # Extract the first provided 'q' parameter, default to empty string if missing
        search_term = query_params.get('q', [''])[0]
        
        logger.info(f"User executed log search query: {search_term}")

        # Filter the mock database based on the search term
        results = [log for log in SYSTEM_LOGS if search_term.lower() in log['msg'].lower()]

        self.send_response(200)
        self.send_header("Content-type", "text/html; charset=utf-8")
        self.end_headers()

        # VULNERABLE SINK: 'search_term' is embedded directly into the HTML string without escaping.
        html = f"""
        <!DOCTYPE html>
        <html lang="en">
        <head>
            <meta charset="UTF-8">
            <title>Search Results</title>
            <style>
                body {{ font-family: 'Courier New', Courier, monospace; background: #f4f4f4; padding: 20px; }}
                .container {{ background: #fff; padding: 20px; border: 1px solid #ccc; max-width: 900px; margin: auto; }}
                .query {{ color: #d35400; font-weight: bold; background: #eee; padding: 2px 5px; }}
                table {{ width: 100%; border-collapse: collapse; margin-top: 20px; }}
                th, td {{ padding: 10px; border: 1px solid #ddd; text-align: left; }}
                th {{ background: #2c3e50; color: white; }}
                .INFO {{ color: #2980b9; font-weight: bold; }}
                .WARNING {{ color: #f39c12; font-weight: bold; }}
                .ERROR {{ color: #c0392b; font-weight: bold; }}
            </style>
        </head>
        <body>
            <div class="container">
                <h2>Log Search Results</h2>
                
                <!-- XSS Injection Point -->
                <p>Found {len(results)} results for query: <span class="query">{search_term}</span></p>
                
                <table>
                    <tr>
                        <th>ID</th>
                        <th>Level</th>
                        <th>Message</th>
                        <th>Timestamp</th>
                    </tr>
        """

        for log in results:
            html += f"""
                    <tr>
                        <td>{log['id']}</td>
                        <td class="{log['level']}">{log['level']}</td>
                        <td>{log['msg']}</td>
                        <td>{log['timestamp']}</td>
                    </tr>
            """

        html += """
                </table>
                <br>
                <a href="/" style="display: inline-block; padding: 10px; background: #2c3e50; color: white; text-decoration: none;">&larr; Back to Search</a>
            </div>
        </body>
        </html>
        """
        
        self.wfile.write(html.encode("utf-8"))

def start_server():
    """Initializes and starts the standard library TCP/HTTP server."""
    handler = LogViewerRequestHandler
    
    # Allow port reuse to prevent "Address already in use" errors during restart
    socketserver.TCPServer.allow_reuse_address = True
    
    with socketserver.TCPServer(("", PORT), handler) as httpd:
        logger.info(f"Serving native Python HTTP server on port {PORT}...")
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            logger.info("Keyboard interrupt received. Shutting down server.")
            httpd.server_close()

if __name__ == "__main__":
    start_server()
