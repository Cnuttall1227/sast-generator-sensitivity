import logging
import sys
from bottle import Bottle, request, response, run

# Configure logging for the IT Support Helpdesk System
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    stream=sys.stdout
)
logger = logging.getLogger("HelpdeskApp")

# Initialize the Bottle application
app = Bottle()

# Mock database of support tickets
SUPPORT_TICKETS = [
    {"id": "TCK-1001", "user": "alice.smith", "issue": "Cannot connect to VPN", "status": "Open", "priority": "High"},
    {"id": "TCK-1002", "user": "bob.jones", "issue": "Printer on 4th floor is out of toner", "status": "Resolved", "priority": "Low"},
    {"id": "TCK-1003", "user": "charlie.brown", "issue": "Laptop screen flickering", "status": "In Progress", "priority": "Medium"},
    {"id": "TCK-1004", "user": "diana.prince", "issue": "Request access to shared drive", "status": "Open", "priority": "Medium"},
    {"id": "TCK-1005", "user": "evan.wright", "issue": "Password reset required", "status": "Resolved", "priority": "High"}
]

@app.route('/')
def dashboard():
    """Main dashboard displaying the search interface and recent tickets."""
    logger.info(f"Dashboard accessed from {request.remote_addr}")
    
    html = """
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <title>IT Support Helpdesk</title>
        <style>
            body { font-family: 'Helvetica Neue', Helvetica, Arial, sans-serif; background-color: #f0f2f5; color: #1c1e21; margin: 0; }
            .header { background-color: #34495e; color: #ecf0f1; padding: 20px 40px; display: flex; justify-content: space-between; align-items: center; }
            .header h1 { margin: 0; font-size: 24px; }
            .content { max-width: 1200px; margin: 30px auto; padding: 0 20px; }
            .search-box { background: white; padding: 25px; border-radius: 8px; box-shadow: 0 2px 4px rgba(0,0,0,0.1); margin-bottom: 30px; }
            .search-box h2 { margin-top: 0; color: #2c3e50; }
            input[type="text"] { width: 70%; padding: 12px; border: 1px solid #bdc3c7; border-radius: 4px; font-size: 16px; }
            button { padding: 12px 24px; background-color: #3498db; color: white; border: none; border-radius: 4px; font-size: 16px; cursor: pointer; }
            button:hover { background-color: #2980b9; }
            table { width: 100%; border-collapse: collapse; background: white; box-shadow: 0 2px 4px rgba(0,0,0,0.1); }
            th, td { padding: 15px; text-align: left; border-bottom: 1px solid #ecf0f1; }
            th { background-color: #ecf0f1; color: #2c3e50; }
            tr:hover { background-color: #f9f9f9; }
            .status-open { color: #e74c3c; font-weight: bold; }
            .status-resolved { color: #27ae60; font-weight: bold; }
        </style>
    </head>
    <body>
        <div class="header">
            <h1>IT Support Helpdesk</h1>
            <div>Logged in as: Admin</div>
        </div>
        <div class="content">
            <div class="search-box">
                <h2>Search Tickets</h2>
                <form action="/search" method="GET">
                    <input type="text" name="q" placeholder="Enter keyword, username, or ticket ID..." required>
                    <button type="submit">Search</button>
                </form>
            </div>
            
            <h2>Recent Tickets</h2>
            <table>
                <tr>
                    <th>Ticket ID</th>
                    <th>User</th>
                    <th>Issue Description</th>
                    <th>Priority</th>
                    <th>Status</th>
                </tr>
    """
    
    for t in SUPPORT_TICKETS:
        status_class = "status-open" if t['status'] != "Resolved" else "status-resolved"
        html += f"""
                <tr>
                    <td>{t['id']}</td>
                    <td>{t['user']}</td>
                    <td>{t['issue']}</td>
                    <td>{t['priority']}</td>
                    <td class="{status_class}">{t['status']}</td>
                </tr>
        """
        
    html += """
            </table>
        </div>
    </body>
    </html>
    """
    return html

import html

@app.route('/search')
def search_tickets():
    """
    FIXED: CWE-79 Cross-Site Scripting (XSS)
    Context: Reflected XSS via HTTP GET Request Query Parameter.
    
    The 'search_query' extracted from the GET request is now properly 
    HTML-escaped before being rendered into the HTML DOM, neutralizing 
    any malicious script payloads.
    """
    # Extract the unvalidated query parameter from the GET request
    search_query = request.query.get('q', '')
    
    logger.info(f"Admin searched for: {search_query}")
    
    # Filter tickets based on the search query
    results = []
    for t in SUPPORT_TICKETS:
        if search_query.lower() in t['issue'].lower() or search_query.lower() in t['user'].lower() or search_query.lower() == t['id'].lower():
            results.append(t)
            
    # FIXED SINK: Escape the untrusted query parameter to prevent HTML/JS injection.
    # This safely converts characters like '<', '>', '&', '"', and "'" to their 
    # respective HTML entities.
    safe_search_query = html.escape(search_query)
            
    html_response = f"""
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <title>Search Results - Helpdesk</title>
        <style>
            body {{ font-family: 'Helvetica Neue', Helvetica, Arial, sans-serif; background-color: #f0f2f5; color: #1c1e21; margin: 0; }}
            .header {{ background-color: #34495e; color: #ecf0f1; padding: 20px 40px; display: flex; justify-content: space-between; align-items: center; }}
            .content {{ max-width: 1200px; margin: 30px auto; padding: 0 20px; }}
            .results-header {{ background: white; padding: 20px; border-radius: 8px; box-shadow: 0 2px 4px rgba(0,0,0,0.1); margin-bottom: 20px; border-left: 5px solid #3498db; }}
            table {{ width: 100%; border-collapse: collapse; background: white; box-shadow: 0 2px 4px rgba(0,0,0,0.1); }}
            th, td {{ padding: 15px; text-align: left; border-bottom: 1px solid #ecf0f1; }}
            th {{ background-color: #ecf0f1; color: #2c3e50; }}
            .back-link {{ display: inline-block; margin-top: 20px; text-decoration: none; color: #3498db; font-weight: bold; }}
        </style>
    </head>
    <body>
        <div class="header">
            <h1 style="margin:0; font-size:24px;">IT Support Helpdesk</h1>
        </div>
        <div class="content">
            <!-- FIXED: Safely escaped variable reflected here -->
            <div class="results-header">
                <h2>Search Results for: <span style="color: #c0392b;">{safe_search_query}</span></h2>
                <p>Found {len(results)} matching tickets.</p>
            </div>
    """
    
    if results:
        html_response += """
            <table>
                <tr>
                    <th>Ticket ID</th>
                    <th>User</th>
                    <th>Issue Description</th>
                    <th>Status</th>
                </tr>
        """
        for t in results:
            # FIXED SINK (Defense in Depth): Escape data retrieved from the mock database
            safe_id = html.escape(t['id'])
            safe_user = html.escape(t['user'])
            safe_issue = html.escape(t['issue'])
            safe_status = html.escape(t['status'])
            
            html_response += f"""
                <tr>
                    <td>{safe_id}</td>
                    <td>{safe_user}</td>
                    <td>{safe_issue}</td>
                    <td>{safe_status}</td>
                </tr>
            """
        html_response += "</table>"
    else:
        html_response += "<p style='background: white; padding: 20px;'>No results found. Please try a different keyword.</p>"
        
    html_response += """
            <a href="/" class="back-link">&larr; Back to Dashboard</a>
        </div>
    </body>
    </html>
    """
    
    return html_response

if __name__ == '__main__':
    port = 8080
    logger.info(f"Starting Bottle IT Helpdesk App on port {port}...")
    # Run the bottle development server
    run(app, host='0.0.0.0', port=port, quiet=True)
