import os
import sys
import logging
from datetime import datetime
from django.conf import settings
from django.core.management import execute_from_command_line
from django.http import HttpResponse, HttpResponseNotFound
from django.urls import path
from django.core.wsgi import get_wsgi_application

# 1. Configure Django settings dynamically (Single-file Django approach)
if not settings.configured:
    settings.configure(
        DEBUG=True,
        SECRET_KEY='insecure-dataset-secret-key-do-not-use-in-prod',
        ROOT_URLCONF=__name__,
        ALLOWED_HOSTS=['*'],
        LOGGING={
            'version': 1,
            'disable_existing_loggers': False,
            'handlers': {
                'console': {
                    'class': 'logging.StreamHandler',
                },
            },
            'root': {
                'handlers': ['console'],
                'level': 'INFO',
            },
        }
    )

logger = logging.getLogger(__name__)

# 2. Mock Database for Portfolios
PORTFOLIOS = {
    "johndoe": {
        "name": "John Doe",
        "bio": "Full Stack Software Engineer & Open Source Contributor",
        "links": ["https://github.com", "https://linkedin.com"]
    },
    "alicesmith": {
        "name": "Alice Smith",
        "bio": "Machine Learning Researcher | Data Scientist",
        "links": ["https://kaggle.com", "https://arxiv.org"]
    }
}

# 3. Views
def index(request):
    """Home page directory listing available portfolios."""
    html = """
    <!DOCTYPE html>
    <html>
    <head><title>Developer Portfolios</title></head>
    <body style="font-family: sans-serif; padding: 2rem;">
        <h1>Developer Portfolios</h1>
        <ul>
    """
    for user in PORTFOLIOS.keys():
        html += f'<li><a href="/portfolio/{user}">{user}</a></li>'
    html += "</ul></body></html>"
    return HttpResponse(html)


import html

def view_portfolio(request, username):
    """
    FIXED: CWE-79 Cross-Site Scripting (XSS)
    The 'theme' query parameter is now properly HTML-escaped before being
    inserted into the HTML attribute, preventing attribute breakout.
    """
    if username not in PORTFOLIOS:
        return HttpResponseNotFound("<h1>Portfolio not found</h1>")
        
    data = PORTFOLIOS[username]
    
    # User-controlled input via GET parameter
    theme_file = request.GET.get('theme', 'default.css')
    
    logger.info(f"Rendering portfolio for {username} with theme {theme_file}")

    # FIXED SINK: Escape the user input before inserting it into the HTML attribute.
    # html.escape() safely encodes characters like '"', '<', and '>' into their 
    # HTML entity equivalents (e.g., &quot;, &lt;, &gt;). This prevents an attacker 
    # from breaking out of the href attribute to inject <script> tags.
    safe_theme_file = html.escape(theme_file)
    
    # Note for defense in depth: For file inclusions like stylesheets, strict allowlisting
    # is the safest approach to prevent CSS injection (loading attacker-controlled CSS).
    # Example: safe_theme_file = theme_file if theme_file in ['dark.css', 'light.css'] else 'default.css'
    
    html_response = f"""
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <title>{data['name']}'s Portfolio</title>
        
        <!-- FIXED: Untrusted input is properly HTML-escaped -->
        <link rel="stylesheet" type="text/css" href="{safe_theme_file}">
        
        <style>
            body {{ font-family: sans-serif; padding: 2rem; max-width: 800px; margin: 0 auto; }}
            .bio {{ font-size: 1.2rem; color: #555; border-left: 4px solid #007bff; padding-left: 1rem; }}
            ul {{ list-style-type: square; }}
        </style>
    </head>
    <body>
        <header>
            <h1>{data['name']}</h1>
            <p class="bio">{data['bio']}</p>
        </header>
        <main>
            <h2>My Links</h2>
            <ul>
    """
    
    # Render links safely assuming they are trusted from the backend database
    for link in data['links']:
        # To be completely safe, database content rendered into attributes should also be escaped
        safe_link = html.escape(link)
        html_response += f'<li><a href="{safe_link}" target="_blank">{safe_link}</a></li>'
        
    html_response += """
            </ul>
        </main>
        <footer>
            <hr>
            <small>Page generated dynamically on """ + datetime.now().strftime("%Y-%m-%d %H:%M:%S") + """</small>
        </footer>
    </body>
    </html>
    """
    
    return HttpResponse(html_response)

# 4. URL Routing Definition
urlpatterns = [
    path('', index),
    path('portfolio/<str:username>', view_portfolio),
]


# 5. WSGI Application entry point and server startup
application = get_wsgi_application()

if __name__ == "__main__":
    logger.info("Starting Minimal Django Portfolio App...")
    logger.info("Access the app at: http://127.0.0.1:8000")
    # To run: python script.py runserver 8000
    execute_from_command_line(sys.argv)
