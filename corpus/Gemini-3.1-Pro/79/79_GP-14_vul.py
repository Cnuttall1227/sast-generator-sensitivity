import bottle
from bottle import request, response, route, run, HTTPError
import logging
import sys
import time
from datetime import datetime

# Configure logging for the Server Log Dashboard
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    stream=sys.stdout
)
logger = logging.getLogger("SysLogViewer")

# Mock database of system logs
MOCK_LOGS = [
    {"timestamp": "2023-10-15 08:12:01", "level": "INFO", "service": "auth-service", "message": "User admin successfully logged in."},
    {"timestamp": "2023-10-15 08:15:33", "level": "WARNING", "service": "payment-api", "message": "High latency detected on gateway."},
    {"timestamp": "2023-10-15 08:17:42", "level": "ERROR", "service": "db-cluster", "message": "Connection timeout to replica node 3."},
    {"timestamp": "2023-10-15 08:22:10", "level": "INFO", "service": "frontend-web", "message": "Deployment v2.4.1 rolled out."},
    {"timestamp": "2023-10-15 08:30:05", "level": "CRITICAL", "service": "auth-service", "message": "Multiple failed login attempts detected from IP 192.168.1.105."}
]

app = bottle.Bottle()

def generate_navbar():
    """Generates the common navigation bar for the dashboard."""
    return """
    <div class="navbar">
        <div class="logo">SysLog Viewer v1.0</div>
        <div class="links">
            <a href="/">Dashboard</a>
            <a href="/search">Search Logs</a>
        </div>
    </div>
    """

@app.route('/')
def index():
    """Dashboard homepage listing recent system events."""
    logger.info("Accessing main dashboard.")
    response.content_type = 'text/html; charset=UTF-8'
    
    html = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <title>SysLog Dashboard</title>
        <style>
            body {{ font-family: 'Helvetica Neue', Helvetica, Arial, sans-serif; background: #f4f7f6; margin: 0; color: #333; }}
            .navbar {{ background: #2c3e50; color: white; padding: 15px 20px; display: flex; justify-content: space-between; }}
            .navbar a {{ color: #ecf0f1; text-decoration: none; margin-left: 15px; font-weight: bold; }}
            .container {{ padding: 30px; max-width: 1000px; margin: 0 auto; }}
            .card {{ background: white; padding: 20px; border-radius: 5px; box-shadow: 0 2px 5px rgba(0,0,0,0.1); }}
            table {{ width: 100%; border-collapse: collapse; margin-top: 15px; }}
            th, td {{ padding: 10px; border-bottom: 1px solid #ddd; text-align: left; }}
            th {{ background-color: #f8f9fa; }}
            .level-INFO {{ color: #2980b9; }}
            .level-WARNING {{ color: #f39c12; }}
            .level-ERROR, .level-CRITICAL {{ color: #c0392b; font-weight: bold; }}
        </style>
    </head>
    <body>
        {generate_navbar()}
        <div class="container">
            <div class="card">
                <h2>Recent System Events</h2>
                <p>Showing the top 5 most recent log entries across all microservices.</p>
                <table>
                    <tr><th>Timestamp</th><th>Level</th><th>Service</th><th>Message</th></tr>
    """
    
    for log in MOCK_LOGS:
        html += f"""<tr>
            <td>{log['timestamp']}</td>
            <td class="level-{log['level']}">{log['level']}</td>
            <td>{log['service']}</td>
            <td>{log['message']}</td>
        </tr>"""
        
    html += """
                </table>
            </div>
        </div>
    </body>
    </html>
    """
    return html

@app.route('/search')
def search_logs():
    """
    VULNERABLE FUNCTION: CWE-79 Cross-Site Scripting (XSS)
    Context: Reflected XSS via HTTP Query String Parameter.
    
    This function implements a search feature that allows users to filter logs.
    It retrieves the 'q' parameter from the URL query string and directly 
    interpolates it into the HTML output without any validation or HTML encoding.
    
    Trigger Path:
    An attacker crafts a URL containing a malicious JavaScript payload in the 'q' 
    parameter, such as: http://target.local:8080/search?q=<script>alert('XSS')</script>
    When a victim clicks this link, the Bottle server reflects the payload into the 
    response page. The victim's browser then executes the script in the context of 
    the web application.
    """
    # Retrieve the search query parameter from the URL
    search_query = request.query.q or ""
    
    logger.info(f"User initiated log search for query: {search_query}")
    response.content_type = 'text/html; charset=UTF-8'

    # Filter logs based on the query (case-insensitive)
    results = [log for log in MOCK_LOGS if search_query.lower() in log['message'].lower() or search_query.lower() in log['service'].lower()]

    # VULNERABLE SINK: The 'search_query' variable is concatenated directly into 
    # the DOM as visible text inside the <h2> tag without sanitization.
    html = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <title>Search Results</title>
        <style>
            body {{ font-family: 'Helvetica Neue', Helvetica, Arial, sans-serif; background: #f4f7f6; margin: 0; color: #333; }}
            .navbar {{ background: #2c3e50; color: white; padding: 15px 20px; display: flex; justify-content: space-between; }}
            .navbar a {{ color: #ecf0f1; text-decoration: none; margin-left: 15px; font-weight: bold; }}
            .container {{ padding: 30px; max-width: 1000px; margin: 0 auto; }}
            .card {{ background: white; padding: 20px; border-radius: 5px; box-shadow: 0 2px 5px rgba(0,0,0,0.1); }}
            .search-box {{ margin-bottom: 20px; padding: 15px; background: #e8eaed; border-radius: 4px; }}
            input[type="text"] {{ padding: 8px; width: 300px; border: 1px solid #ccc; border-radius: 3px; }}
            input[type="submit"] {{ padding: 8px 15px; background: #3498db; color: white; border: none; border-radius: 3px; cursor: pointer; }}
            ul {{ list-style-type: none; padding: 0; }}
            li {{ padding: 12px; border-bottom: 1px solid #eee; }}
            .keyword {{ color: #e74c3c; font-weight: bold; }}
        </style>
    </head>
    <body>
        {generate_navbar()}
        <div class="container">
            <div class="card">
                <div class="search-box">
                    <form action="/search" method="GET">
                        <label>Keyword: </label>
                        <input type="text" name="q" placeholder="Enter service or message keyword...">
                        <input type="submit" value="Search">
                    </form>
                </div>
                
                <!-- Injection Point: Unescaped query string parameter reflected here -->
                <h2>Search Results for: <span class="keyword">'{search_query}'</span></h2>
                
                <p>Found {len(results)} matching entries.</p>
                <ul>
    """
    
    if results:
        for log in results:
            html += f"<li><strong>[{log['timestamp']}] {log['service']}:</strong> {log['message']}</li>"
    elif search_query:
        html += "<li>No results found matching your criteria.</li>"
    else:
        html += "<li>Please enter a search term above.</li>"
        
    html += """
                </ul>
            </div>
        </div>
    </body>
    </html>
    """
    
    return html

if __name__ == "__main__":
    port = 8080
    logger.info(f"Starting Bottle SysLog Interface on port {port}...")
    try:
        run(app, host='0.0.0.0', port=port, quiet=True)
    except KeyboardInterrupt:
        logger.info("Shutting down Server Log Dashboard.")
        sys.exit(0)
