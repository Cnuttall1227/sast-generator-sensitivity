import os
import sys
import logging
import uuid
from datetime import datetime
from bottle import Bottle, request, response, run, HTTPError

# --- Setup Logging ---
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    stream=sys.stdout
)
logger = logging.getLogger('AssetManagerApp')

app = Bottle()

# --- Mock Database ---
ASSET_REGISTRY = [
    {"id": "ast-001", "name": "logo.png", "size": 1024, "date": "2023-11-20"},
    {"id": "ast-002", "name": "styles.css", "size": 4096, "date": "2023-11-21"}
]

@app.route('/')
def home():
    """Renders the main dashboard for the Asset Management System."""
    logger.info("Accessing home dashboard.")
    
    html = """
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <title>Asset Manager Dashboard</title>
        <style>
            body { font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; margin: 40px; background-color: #f4f7f6; color: #333; }
            .container { max-width: 800px; margin: auto; background: white; padding: 30px; border-radius: 8px; box-shadow: 0 4px 10px rgba(0,0,0,0.1); }
            h1 { color: #2c3e50; border-bottom: 2px solid #3498db; padding-bottom: 10px; }
            .upload-box { border: 2px dashed #bdc3c7; padding: 20px; text-align: center; margin-bottom: 30px; border-radius: 5px; background: #fafafa; }
            .upload-btn { background: #3498db; color: white; border: none; padding: 10px 20px; cursor: pointer; border-radius: 3px; font-size: 16px; margin-top: 10px; }
            .upload-btn:hover { background: #2980b9; }
            table { width: 100%; border-collapse: collapse; margin-top: 20px; }
            th, td { padding: 12px; border-bottom: 1px solid #ddd; text-align: left; }
            th { background-color: #ecf0f1; color: #2c3e50; }
        </style>
    </head>
    <body>
        <div class="container">
            <h1>Digital Asset Manager</h1>
            
            <div class="upload-box">
                <h3>Upload New Asset</h3>
                <form action="/upload" method="POST" enctype="multipart/form-data">
                    <input type="file" name="asset_file" required>
                    <br>
                    <button type="submit" class="upload-btn">Upload File</button>
                </form>
            </div>
            
            <h3>Existing Assets</h3>
            <table>
                <tr>
                    <th>ID</th>
                    <th>Filename</th>
                    <th>Size (Bytes)</th>
                    <th>Upload Date</th>
                </tr>
    """
    
    for asset in ASSET_REGISTRY:
        html += f"""
                <tr>
                    <td>{asset['id']}</td>
                    <td>{asset['name']}</td>
                    <td>{asset['size']}</td>
                    <td>{asset['date']}</td>
                </tr>
        """
        
    html += """
            </table>
        </div>
    </body>
    </html>
    """
    return html

@app.route('/upload', method='POST')
def process_upload():
    """
    VULNERABLE FUNCTION: CWE-79 Cross-Site Scripting (XSS)
    Context: Reflected XSS via Multipart Form Filename.
    
    When a file is uploaded, the application extracts the 'filename' attribute 
    from the Content-Disposition header of the multipart/form-data payload.
    It then directly reflects this filename in the HTML success response without
    HTML entity encoding.
    
    Trigger:
    An attacker can intercept the upload request and modify the filename parameter:
    Content-Disposition: form-data; name="asset_file"; filename="<script>alert(document.cookie)</script>.png"
    
    When the server responds, the malicious filename is embedded into the DOM, 
    executing the script in the user's browser context.
    """
    upload = request.files.get('asset_file')
    
    if not upload:
        return HTTPError(400, "No file provided in the request.")
        
    # Extract the raw filename provided by the client
    raw_filename = upload.filename
    logger.info(f"Processing upload for file: {raw_filename}")
    
    # Simulate saving the file and generating metadata
    new_asset = {
        "id": f"ast-{uuid.uuid4().hex[:4]}",
        "name": raw_filename,
        "size": 2048, # Mock size mapping
        "date": datetime.now().strftime("%Y-%m-%d")
    }
    
    # In a real app, this would be saved persistently. 
    # For this example, we just append it to the in-memory store.
    ASSET_REGISTRY.append(new_asset)
    
    # VULNERABLE SINK: The untrusted 'raw_filename' is concatenated directly into the HTML string.
    response.content_type = 'text/html; charset=UTF8'
    html_response = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <title>Upload Successful</title>
        <style>
            body {{ font-family: sans-serif; background: #e8f5e9; color: #2e7d32; display: flex; justify-content: center; align-items: center; height: 100vh; margin: 0; }}
            .msg-box {{ background: white; padding: 40px; border-radius: 8px; box-shadow: 0 4px 6px rgba(0,0,0,0.1); text-align: center; border-top: 5px solid #4caf50; }}
            .filename {{ font-family: monospace; background: #eee; padding: 5px; color: #d32f2f; }}
            a {{ display: inline-block; margin-top: 20px; text-decoration: none; color: white; background: #4caf50; padding: 10px 20px; border-radius: 4px; }}
        </style>
    </head>
    <body>
        <div class="msg-box">
            <h2>Upload Completed Successfully</h2>
            <p>Your asset has been securely stored in the registry.</p>
            
            <!-- VULNERABLE INJECTION POINT -->
            <p>Asset Name: <span class="filename">{raw_filename}</span></p>
            
            <a href="/">Return to Dashboard</a>
        </div>
    </body>
    </html>
    """
    
    return html_response

if __name__ == '__main__':
    logger.info("Starting Bottle Asset Manager server on port 8080...")
    # Run the lightweight bottle web server
    run(app, host='0.0.0.0', port=8080, quiet=True)
