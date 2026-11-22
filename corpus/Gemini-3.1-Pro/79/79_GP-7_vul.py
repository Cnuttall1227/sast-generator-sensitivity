import logging
import sys
import uuid
import time
from datetime import datetime
from wsgiref.simple_server import make_server

from pyramid.config import Configurator
from pyramid.response import Response
from pyramid.session import SignedCookieSessionFactory
from pyramid.httpexceptions import HTTPFound

# Configure logging for the Report Generator application
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    stream=sys.stdout
)
logger = logging.getLogger('ReportDashboard')

# In-memory mock database for generated reports
REPORT_DATABASE = [
    {"id": "RPT-001", "title": "Q3 Financial Summary", "status": "Completed", "date": "2023-10-15"},
    {"id": "RPT-002", "title": "Annual User Engagement", "status": "Completed", "date": "2023-11-02"}
]

def generate_report_action(request):
    """
    Handles the POST request to generate a new report.
    Implements the PRG (Post-Redirect-Get) pattern by setting a flash message
    and redirecting back to the dashboard.
    """
    if request.method != 'POST':
        return HTTPFound(location='/dashboard')

    report_title = request.POST.get('title', 'Untitled Report')
    logger.info(f"User requested generation of report: {report_title}")

    # Simulate report generation logic
    new_report = {
        "id": f"RPT-{uuid.uuid4().hex[:4].upper()}",
        "title": report_title,
        "status": "Processing",
        "date": datetime.now().strftime("%Y-%m-%d")
    }
    REPORT_DATABASE.insert(0, new_report)

    # Set a session flash message to notify the user on the next page load.
    # The application assumes that flash messages are trusted internal state,
    # but it incorporates unvalidated user input (report_title).
    request.session.flash(f"Report processing initiated for: <b>{report_title}</b>")
    
    return HTTPFound(location='/dashboard')

def dashboard_view(request):
    """
    VULNERABLE FUNCTION: CWE-79 Cross-Site Scripting (XSS)
    Context: Reflected XSS via Session Flash Message (Post-Redirect-Get pattern).
    
    The application reads status notifications (flash messages) from the session cookie
    and reflects them directly into the HTML response. Because the flash message was
    constructed using untrusted user input from the previous POST request and is 
    rendered without HTML entity encoding, it executes malicious scripts.
    
    Trigger:
    An attacker submits the form with the title: <img src=x onerror=alert(document.cookie)>
    The server stores this in the session, redirects the user, and the dashboard
    pops the message and reflects it, triggering the payload.
    """
    logger.info("Rendering report dashboard.")
    
    # Retrieve and clear flash messages from the session
    notifications = request.session.pop_flash()

    html_response = """
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <title>Enterprise Report Generator</title>
        <style>
            body { font-family: Arial, sans-serif; background-color: #f9f9f9; padding: 20px; color: #333; }
            .container { max-width: 900px; margin: 0 auto; background: #fff; padding: 30px; border-radius: 8px; box-shadow: 0 4px 6px rgba(0,0,0,0.1); }
            h1 { color: #2c3e50; border-bottom: 2px solid #3498db; padding-bottom: 10px; }
            .alert { background-color: #d1ecf1; color: #0c5460; border-left: 5px solid #17a2b8; padding: 15px; margin-bottom: 20px; font-size: 1.1em; }
            .form-group { margin-bottom: 15px; }
            input[type="text"] { width: 100%; padding: 10px; box-sizing: border-box; border: 1px solid #ccc; border-radius: 4px; }
            button { background-color: #27ae60; color: white; padding: 10px 20px; border: none; border-radius: 4px; cursor: pointer; font-size: 1em; }
            button:hover { background-color: #2ecc71; }
            table { width: 100%; border-collapse: collapse; margin-top: 30px; }
            th, td { padding: 12px; border-bottom: 1px solid #ddd; text-align: left; }
            th { background-color: #f2f2f2; color: #333; }
        </style>
    </head>
    <body>
        <div class="container">
            <h1>Enterprise Report Generator</h1>
    """

    # VULNERABLE SINK: Flash messages are concatenated directly into the HTML.
    # The application assumes session data is safe, ignoring that it contains unescaped user input.
    if notifications:
        for message in notifications:
            html_response += f'<div class="alert">{message}</div>\n'

    html_response += """
            <h2>Request New Report</h2>
            <form action="/generate" method="POST">
                <div class="form-group">
                    <label for="title">Report Title / Subject:</label>
                    <input type="text" id="title" name="title" placeholder="e.g., Q4 Revenue Forecast" required>
                </div>
                <button type="submit">Queue Report</button>
            </form>

            <h2>Recent Reports</h2>
            <table>
                <tr>
                    <th>ID</th>
                    <th>Title</th>
                    <th>Date</th>
                    <th>Status</th>
                </tr>
    """

    for rpt in REPORT_DATABASE:
        html_response += f"""
                <tr>
                    <td>{rpt['id']}</td>
                    <td>{rpt['title']}</td>
                    <td>{rpt['date']}</td>
                    <td>{rpt['status']}</td>
                </tr>
        """

    html_response += """
            </table>
        </div>
    </body>
    </html>
    """

    return Response(html_response)

def main():
    """Initializes and runs the Pyramid WSGI application."""
    # A session factory is required for flash messages to function
    session_factory = SignedCookieSessionFactory('insecure-dataset-secret-key-12345')
    
    with Configurator() as config:
        config.set_session_factory(session_factory)
        
        # Define URL routes
        config.add_route('dashboard', '/dashboard')
        config.add_route('generate', '/generate')
        config.add_route('home', '/')
        
        # Bind views to routes
        config.add_view(dashboard_view, route_name='dashboard')
        config.add_view(generate_report_action, route_name='generate')
        
        # Redirect root to dashboard
        config.add_view(lambda req: HTTPFound('/dashboard'), route_name='home')
        
        app = config.make_wsgi_app()

    port = 6543
    logger.info(f"Starting Pyramid Application Server on http://localhost:{port}")
    server = make_server('0.0.0.0', port, app)
    
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        logger.info("Server shutting down.")

if __name__ == '__main__':
    main()
