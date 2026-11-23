import os
import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse, FileResponse
import logging

# Setup logging configuration for the API
logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')
logger = logging.getLogger("AvatarService")

# Initialize FastAPI application
app = FastAPI(title="Corporate Team Directory", version="1.0")

# Configuration constants
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
AVATAR_DIR = os.path.join(BASE_DIR, "avatars")

# Mock database of users for the directory
USERS = [
    {"id": 1, "name": "Alice Smith", "role": "CEO", "avatar": "alice.png"},
    {"id": 2, "name": "Bob Jones", "role": "Lead Developer", "avatar": "bob.png"},
    {"id": 3, "name": "Charlie Brown", "role": "UX Designer", "avatar": "charlie.png"}
]

def initialize_dummy_avatars():
    """Ensure the avatar directory exists and populate it with placeholder files."""
    if not os.path.exists(AVATAR_DIR):
        os.makedirs(AVATAR_DIR)
        
    for user in USERS:
        avatar_path = os.path.join(AVATAR_DIR, user["avatar"])
        if not os.path.exists(avatar_path):
            # Create a dummy text file pretending to be an image to satisfy FileResponse
            with open(avatar_path, "w") as f:
                f.write(f"Mock image binary data for {user['name']}")
                
    logger.info(f"Initialized avatar storage directory at {AVATAR_DIR}")

@app.on_event("startup")
async def startup_event():
    initialize_dummy_avatars()

@app.get("/", response_class=HTMLResponse)
async def directory_dashboard():
    """Renders the main employee directory HTML page."""
    html_content = """
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>Employee Directory</title>
        <style>
            body { font-family: 'Inter', sans-serif; background-color: #f3f4f6; margin: 0; padding: 20px; color: #111827; }
            .header { text-align: center; margin-bottom: 40px; padding: 20px; background: white; border-radius: 8px; box-shadow: 0 1px 3px rgba(0,0,0,0.1); }
            .header h1 { color: #2563eb; margin: 0 0 10px 0; }
            .grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(250px, 1fr)); gap: 20px; max-width: 1000px; margin: 0 auto; }
            .card { background: white; border-radius: 12px; padding: 20px; box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.1); text-align: center; border-top: 4px solid #3b82f6; }
            .avatar-placeholder { width: 100px; height: 100px; background-color: #e5e7eb; border-radius: 50%; margin: 0 auto 15px auto; display: flex; align-items: center; justify-content: center; overflow: hidden; }
            .name { font-size: 1.2rem; font-weight: bold; margin-bottom: 5px; }
            .role { color: #6b7280; margin-bottom: 15px; font-size: 0.9rem; }
            .btn { display: inline-block; background-color: #2563eb; color: white; padding: 8px 16px; border-radius: 6px; text-decoration: none; font-size: 0.9rem; transition: background-color 0.2s; }
            .btn:hover { background-color: #1d4ed8; }
        </style>
    </head>
    <body>
        <div class="header">
            <h1>Corporate Team Directory</h1>
            <p style="margin: 0; color: #4b5563;">Connect with your colleagues.</p>
        </div>
        <div class="grid">
    """
    
    for user in USERS:
        html_content += f"""
            <div class="card">
                <div class="avatar-placeholder">
                    <span style="color: #9ca3af; font-size: 0.8rem;">Image</span>
                </div>
                <div class="name">{user['name']}</div>
                <div class="role">{user['role']}</div>
                <a href="/api/v1/avatar/download?filename={user['avatar']}" class="btn">Download Avatar</a>
            </div>
        """
        
    html_content += """
        </div>
    </body>
    </html>
    """
    return html_content

import os
from fastapi import HTTPException
from fastapi.responses import FileResponse

@app.get("/api/v1/avatar/download")
async def download_user_avatar(filename: str):
    """
    FIXED: CWE-22 Path Traversal
    Context: Downloading a user's avatar image via a FastAPI endpoint.
    
    The 'filename' parameter is now strictly validated to ensure that the resolved 
    absolute path of the requested file remains inside the intended AVATAR_DIR.
    This neutralizes directory traversal sequences like '../' and absolute 
    path injections.
    """
    if not filename:
        raise HTTPException(status_code=400, detail="Filename parameter is required")
        
    logger.info(f"Requested avatar download for: {filename}")
    
    # FIXED SINK: Secure path resolution to prevent CWE-22
    # 1. Get the absolute path of the intended base directory
    abs_base_dir = os.path.abspath(AVATAR_DIR)
    
    # 2. Construct the requested path and resolve its absolute path
    target_path = os.path.abspath(os.path.join(abs_base_dir, filename))
    
    # 3. Verify the resolved path is strictly within the base directory
    # os.path.commonpath is immune to partial directory name bypasses
    if os.path.commonpath([abs_base_dir, target_path]) != abs_base_dir:
        logger.warning(f"Path traversal attempt blocked: {filename}")
        raise HTTPException(status_code=403, detail="Invalid file path")
    
    logger.debug(f"Resolved absolute file path: {target_path}")
    
    if not os.path.exists(target_path):
        logger.error(f"Avatar file not found on disk: {target_path}")
        raise HTTPException(status_code=404, detail="Avatar not found")
        
    try:
        # FileResponse now safely serves the file after path validation.
        return FileResponse(
            path=target_path, 
            filename=os.path.basename(target_path),
            media_type="application/octet-stream"
        )
    except Exception as e:
        logger.error(f"Error serving file: {str(e)}")
        raise HTTPException(status_code=500, detail="Internal server error occurred")

if __name__ == "__main__":
    logger.info("Starting Corporate Directory API server on port 8000...")
    # Run the uvicorn ASGI server
    uvicorn.run(app, host="0.0.0.0", port=8000, log_level="info")
