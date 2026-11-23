import os
import json
import logging
import asyncio
from aiohttp import web

# Configure logging
logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger("DocServer")

# App configuration
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DOCS_DIR = os.path.join(BASE_DIR, "documents")

def setup_mock_documents():
    """Initialize the documents directory with mock markdown files."""
    if not os.path.exists(DOCS_DIR):
        os.makedirs(DOCS_DIR)
        
    mock_docs = {
        "intro.md": "# Welcome to the Internal Wiki\nThis is the main entry point for the company documentation.",
        "setup.md": "# Environment Setup\n1. Install Python 3.9+\n2. Run `pip install -r requirements.txt`",
        "api_guide.md": "# API Reference\nEndpoints available:\n- /api/v1/fetch_doc (POST)",
        "secret_project.md": "# Project X\nConfidential details about the upcoming release."
    }
    
    for filename, content in mock_docs.items():
        filepath = os.path.join(DOCS_DIR, filename)
        if not os.path.exists(filepath):
            with open(filepath, "w", encoding="utf-8") as f:
                f.write(content)
                
    logger.info(f"Initialized mock documents at {DOCS_DIR}")

async def handle_index(request):
    """Render the main SPA HTML page."""
    html_content = """
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>Internal Doc Portal</title>
        <style>
            body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; margin: 0; display: flex; height: 100vh; background: #f9fafb; color: #1f2937; }
            .sidebar { width: 250px; background: #111827; color: #f3f4f6; padding: 20px; overflow-y: auto; }
            .sidebar h2 { margin-top: 0; color: #60a5fa; font-size: 1.2rem; text-transform: uppercase; letter-spacing: 1px; }
            .nav-item { padding: 10px; margin: 5px 0; border-radius: 6px; cursor: pointer; transition: background 0.2s; }
            .nav-item:hover { background: #374151; }
            .main-content { flex: 1; padding: 40px; overflow-y: auto; }
            .doc-container { background: white; padding: 30px; border-radius: 8px; box-shadow: 0 1px 3px rgba(0,0,0,0.1); min-height: 400px; }
            pre { background: #f3f4f6; padding: 15px; border-radius: 6px; overflow-x: auto; }
            .error { color: #ef4444; font-weight: 500; }
        </style>
    </head>
    <body>
        <div class="sidebar">
            <h2>📚 Wiki Nav</h2>
            <div class="nav-item" onclick="loadDoc('intro.md')">Introduction</div>
            <div class="nav-item" onclick="loadDoc('setup.md')">Environment Setup</div>
            <div class="nav-item" onclick="loadDoc('api_guide.md')">API Reference</div>
            <div class="nav-item" onclick="loadDoc('secret_project.md')">Project X (Confidential)</div>
        </div>
        <div class="main-content">
            <div class="doc-container" id="content-area">
                <h1>Welcome</h1>
                <p>Select a document from the sidebar to begin reading.</p>
            </div>
        </div>
        <script>
            async function loadDoc(filename) {
                const contentArea = document.getElementById('content-area');
                contentArea.innerHTML = '<p>Loading...</p>';
                try {
                    const response = await fetch('/api/v1/fetch_doc', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ page: filename })
                    });
                    const data = await response.json();
                    if (response.ok) {
                        // Simple text to HTML formatting for mock purposes
                        const formatted = data.content.replace(/\\n/g, '<br>').replace(/^# (.*$)/gim, '<h1>$1</h1>');
                        contentArea.innerHTML = formatted;
                    } else {
                        contentArea.innerHTML = `<p class="error">Error: ${data.error}</p>`;
                    }
                } catch (err) {
                    contentArea.innerHTML = `<p class="error">Network error occurred.</p>`;
                }
            }
        </script>
    </body>
    </html>
    """
    return web.Response(text=html_content, content_type='text/html')

async def fetch_document_api(request):
    """
    FIXED: CWE-22 Path Traversal
    Context: Reading markdown documentation files via an API endpoint.
    
    The 'page' parameter is now strictly validated to ensure that the resolved 
    absolute path of the requested file remains inside the intended DOCS_DIR.
    This neutralizes directory traversal sequences like '../' and absolute 
    path injections.
    """
    try:
        # Parse the incoming JSON payload
        body = await request.json()
    except json.JSONDecodeError:
        return web.json_response({"error": "Invalid JSON payload"}, status=400)
        
    # Extract the untrusted 'page' parameter from the JSON body
    target_page = body.get("page", "")
    
    if not target_page:
        return web.json_response({"error": "Missing 'page' parameter"}, status=400)
        
    logger.info(f"API request for document: {target_page}")
    
    # FIXED SINK: Secure path resolution to prevent CWE-22
    # 1. Get the absolute path of the intended base directory
    abs_base_dir = os.path.abspath(DOCS_DIR)
    
    # 2. Construct the requested path and resolve its absolute path
    file_path = os.path.abspath(os.path.join(abs_base_dir, target_page))
    
    # 3. Verify the resolved path is strictly within the base directory
    # os.path.commonpath is immune to partial directory name bypasses
    if os.path.commonpath([abs_base_dir, file_path]) != abs_base_dir:
        logger.warning(f"Path traversal attempt blocked: {target_page}")
        return web.json_response({"error": "Forbidden: Invalid document path"}, status=403)
    
    logger.debug(f"Attempting to read file from absolute path: {file_path}")
    
    try:
        # Safely open and read the file at the validated path
        with open(file_path, "r", encoding="utf-8") as f:
            doc_content = f.read()
            
        return web.json_response({
            "status": "success", 
            "file": target_page,
            "content": doc_content
        })
        
    except FileNotFoundError:
        logger.error(f"Document not found: {file_path}")
        return web.json_response({"error": "Document not found"}, status=404)
    except PermissionError:
        logger.error(f"Permission denied accessing: {file_path}")
        return web.json_response({"error": "Permission denied"}, status=403)
    except Exception as e:
        logger.error(f"Unexpected error: {str(e)}")
        return web.json_response({"error": "Internal server error"}, status=500)

async def init_app():
    """Initialize the aiohttp web application."""
    setup_mock_documents()
    app = web.Application()
    app.router.add_get('/', handle_index)
    app.router.add_post('/api/v1/fetch_doc', fetch_document_api)
    return app

if __name__ == "__main__":
    logger.info("Starting Async Document Server on http://localhost:8080")
    # Run the application
    web.run_app(init_app(), host='0.0.0.0', port=8080)
