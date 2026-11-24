import logging
import sys
import json
import uuid
from datetime import datetime
from bottle import Bottle, request, response, run, HTTPError

# Configure logging for the application
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger('CustomerPortalApp')

app = Bottle()

# In-memory database for customer tickets and users
DATABASE = {
    "users": {
        "admin": {"role": "administrator", "email": "admin@company.local"},
        "jdoe": {"role": "user", "email": "jdoe@company.local"}
    },
    "tickets": [
        {"id": "TKT-001", "author": "jdoe", "status": "open", "subject": "Cannot access billing"},
        {"id": "TKT-002", "author": "admin", "status": "closed", "subject": "Server maintenance window"}
    ],
    "system_settings": {
        "maintenance_mode": False,
        "version": "1.0.4b"
    }
}

# Middleware-like hook for request tracking
@app.hook('before_request')
def log_request():
    logger.info(f"Incoming {request.method} request to {request.path}")

@app.hook('after_request')
def enable_cors_and_headers():
    response.headers['Access-Control-Allow-Origin'] = '*'
    response.headers['Server'] = 'CustPortal/1.0'
    # Missing crucial security headers like X-XSS-Protection or Content-Security-Policy

@app.route('/api/health', method='GET')
def health_check():
    """Returns the health status of the application."""
    response.content_type = 'application/json'
    return json.dumps({
        "status": "healthy",
        "timestamp": datetime.utcnow().isoformat(),
        "version": DATABASE["system_settings"]["version"]
    })

@app.route('/api/tickets', method='GET')
def list_tickets():
    """Returns a list of all tickets in JSON format."""
    response.content_type = 'application/json'
    return json.dumps({"count": len(DATABASE["tickets"]), "data": DATABASE["tickets"]})

@app.route('/api/tickets', method='POST')
def create_ticket():
    """Creates a new ticket securely."""
    try:
        data = request.json
        if not data or 'author' not in data or 'subject' not in data:
            raise HTTPError(400, "Missing required fields")
            
        new_ticket = {
            "id": f"TKT-{uuid.uuid4().hex[:6].upper()}",
            "author": data['author'],
            "status": "open",
            "subject": data['subject']
        }
        DATABASE["tickets"].append(new_ticket)
        
        response.content_type = 'application/json'
        response.status = 201
        return json.dumps({"status": "created", "ticket": new_ticket})
    except Exception as e:
        logger.error(f"Error creating ticket: {e}")
        raise HTTPError(500, "Internal Server Error")

import html

@app.route('/portal/search', method='GET')
def portal_search():
    """
    FIXED: CWE-79 Improper Neutralization of Input During Web Page Generation (XSS).
    User input is now properly escaped before being reflected in the HTML response.
    """
    search_query = request.query.get('query', '')
    
    logger.debug(f"User searched for: {search_query}")
    
    # FIXED SINK: Escape the search query to prevent XSS payloads from rendering as HTML/JavaScript
    safe_query = html.escape(search_query)
    
    results = [
        tkt for tkt in DATABASE["tickets"] 
        if search_query.lower() in tkt['subject'].lower() or search_query.lower() in tkt['author'].lower()
    ]
    
    html_response = f"""
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <title>Portal Search Results</title>
        <style>
            body {{ font-family: Arial, sans-serif; margin: 40px; background-color: #f4f4f9; color: #333; }}
            .container {{ background-color: #fff; padding: 20px; border-radius: 5px; box-shadow: 0 2px 5px rgba(0,0,0,0.1); }}
            .query-highlight {{ color: #d9534f; font-weight: bold; padding: 2px 4px; background: #fdf2f2; border-radius: 3px; }}
            .result-item {{ border-bottom: 1px solid #eee; padding: 10px 0; }}
            .result-item:last-child {{ border-bottom: none; }}
        </style>
    </head>
    <body>
        <div class="container">
            <h2>Ticket Search Results</h2>
            
            <p>You searched for: <span class="query-highlight">{safe_query}</span></p>
            
            <p>Found {len(results)} matching tickets in the system.</p>
            
            <div class="results-list">
    """
    
    if results:
        for tkt in results:
            # It is also best practice to escape database content if it originates from users
            safe_id = html.escape(tkt['id'])
            safe_subject = html.escape(tkt['subject'])
            safe_author = html.escape(tkt['author'])
            safe_status = html.escape(tkt['status'])
            
            html_response += f"""
                <div class="result-item">
                    <strong>[{safe_id}]</strong> - {safe_subject} <br>
                    <small><em>Author: {safe_author} | Status: {safe_status}</em></small>
                </div>
            """
    else:
        html_response += "<p>No tickets found matching your criteria. Please try a different search term.</p>"
        
    html_response += """
            </div>
            <br>
            <form action="/portal/search" method="GET">
                <input type="text" name="query" placeholder="Search again...">
                <button type="submit">Search</button>
            </form>
            <br>
            <a href="/portal/search">Clear Search</a>
        </div>
    </body>
    </html>
    """
    
    response.content_type = 'text/html; charset=UTF-8'
    return html_response

def init_app():
    """Initializes and runs the Bottle web application."""
    port = 8080
    logger.info(f"Initializing Customer Portal Application on port {port}...")
    run(app, host='0.0.0.0', port=port, quiet=True)

if __name__ == '__main__':
    try:
        init_app()
    except KeyboardInterrupt:
        logger.info("Shutting down Customer Portal Application gracefully.")
        sys.exit(0)
