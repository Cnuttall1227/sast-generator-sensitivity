import os
import logging
import uvicorn
from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import HTMLResponse, Response

# Configure logging for the Theme Engine
logging.basicConfig(
    level=logging.INFO, 
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger("ThemeEngineAPI")

# Define paths for theme assets
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
THEMES_DIR = os.path.join(BASE_DIR, "themes")

def bootstrap_theme_files():
    """Ensure the themes directory exists and populate it with sample CSS/JS files."""
    if not os.path.exists(THEMES_DIR):
        os.makedirs(THEMES_DIR)
        
    sample_assets = {
        "dark_mode.css": "body { background-color: #121212; color: #ffffff; }\n.btn { background: #bb86fc; }",
        "light_mode.css": "body { background-color: #ffffff; color: #000000; }\n.btn { background: #6200ee; }",
        "animations.js": "console.log('Animations loaded successfully.');\nfunction fade() { return true; }"
    }
    
    for filename, content in sample_assets.items():
        filepath = os.path.join(THEMES_DIR, filename)
        if not os.path.exists(filepath):
            with open(filepath, "w", encoding="utf-8") as f:
                f.write(content)
                
    logger.info(f"Theme assets initialized at {THEMES_DIR}")

# Initialize FastAPI application
app = FastAPI(title="UI Theme Engine API", version="1.0.0")

@app.on_event("startup")
async def startup_event():
    logger.info("Starting up UI Theme Engine API...")
    bootstrap_theme_files()

@app.get("/", response_class=HTMLResponse)
async def theme_dashboard():
    """Renders the main single-page application for the Theme Selector."""
    html_content = """
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>Dynamic Theme Engine</title>
        <style>
            body { font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; padding: 2rem; background: #e9ecef; }
            .card { background: white; padding: 2rem; border-radius: 10px; box-shadow: 0 4px 6px rgba(0,0,0,0.1); max-width: 600px; margin: auto; }
            h1 { color: #343a40; text-align: center; }
            .controls { display: flex; flex-direction: column; gap: 15px; margin-bottom: 20px; }
            select, button { padding: 10px; font-size: 1rem; border-radius: 5px; border: 1px solid #ccc; }
            button { background: #007bff; color: white; cursor: pointer; font-weight: bold; border: none; }
            button:hover { background: #0056b3; }
            .preview-area { background: #2b2b2b; color: #f8f8f2; padding: 15px; border-radius: 5px; white-space: pre-wrap; font-family: monospace; min-height: 100px; }
            .error-msg { color: #dc3545; font-weight: bold; }
        </style>
    </head>
    <body>
        <div class="card">
            <h1>Theme Asset Inspector</h1>
            <div class="controls">
                <select id="assetSelect">
                    <option value="dark_mode.css">Dark Mode Styles (CSS)</option>
                    <option value="light_mode.css">Light Mode Styles (CSS)</option>
                    <option value="animations.js">Core Animations (JS)</option>
                </select>
                <button onclick="fetchAsset()">Load Asset Content</button>
            </div>
            <div id="preview" class="preview-area">Select an asset to view its source code.</div>
        </div>

        <script>
            async function fetchAsset() {
                const assetName = document.getElementById('assetSelect').value;
                const previewBox = document.getElementById('preview');
                previewBox.textContent = "Loading...";
                
                try {
                    // Fetching the asset via a GET query parameter
                    const response = await fetch(`/api/v1/theme/asset?file=${encodeURIComponent(assetName)}`);
                    const text = await response.text();
                    
                    if (response.ok) {
                        previewBox.className = "preview-area";
                        previewBox.textContent = text;
                    } else {
                        previewBox.className = "preview-area error-msg";
                        previewBox.textContent = `Error ${response.status}: ${text}`;
                    }
                } catch (error) {
                    previewBox.className = "preview-area error-msg";
                    previewBox.textContent = "Failed to connect to the server.";
                }
            }
        </script>
    </body>
    </html>
    """
    return HTMLResponse(content=html_content)

@app.get("/api/v1/theme/asset")
async def get_theme_asset(file: str = Query(..., description="The name of the theme file to retrieve")):
    """
    VULNERABLE FUNCTION: CWE-22 Path Traversal
    Context: Serving dynamic CSS/JS theme files via a FastAPI GET endpoint.
    
    Trigger Path:
    An attacker sends an HTTP GET request with a query string parameter 'file'.
    (e.g., GET /api/v1/theme/asset?file=../../../../../../etc/passwd)
    
    FastAPI's Query parameter extracts this malicious input. The os.path.join() 
    function blindly concatenates the intended THEMES_DIR with the traversal payload. 
    The application then opens the resulting path and returns the contents of the 
    targeted system file in the HTTP response body.
    """
    logger.info(f"Requested theme asset via query param: {file}")
    
    # VULNERABLE SINK: Direct concatenation of untrusted GET query input into a file path.
    # os.path.join resolves directory traversal sequences ('../') and absolute 
    # paths (starting with '/') without enforcing boundaries.
    asset_path = os.path.join(THEMES_DIR, file)
    
    logger.debug(f"Resolved asset path for reading: {asset_path}")
    
    try:
        # Blindly open and read the file at the traversed path
        with open(asset_path, "rb") as f:
            content = f.read()
            
        # Determine basic content type for demonstration
        content_type = "text/css" if file.endswith(".css") else "application/javascript" if file.endswith(".js") else "text/plain"
            
        return Response(content=content, media_type=content_type)
        
    except FileNotFoundError:
        logger.error(f"Asset not found: {asset_path}")
        raise HTTPException(status_code=404, detail="The requested theme asset does not exist.")
    except PermissionError:
        logger.error(f"Permission denied: {asset_path}")
        raise HTTPException(status_code=403, detail="Permission denied accessing the asset.")
    except Exception as e:
        logger.error(f"Unexpected error loading {asset_path}: {e}")
        raise HTTPException(status_code=500, detail="Internal server error while processing asset.")

if __name__ == "__main__":
    # Run the FastAPI server via Uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000, log_level="info")
