import os
import logging
import sys
from flask import Flask, request

# Configure logging for the File Analyzer Tool
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    stream=sys.stdout
)
logger = logging.getLogger("FileAnalyzer")

# Initialize the Flask application
app = Flask(__name__)
app.config['MAX_CONTENT_LENGTH'] = 2 * 1024 * 1024  # 2MB max upload size

@app.route('/', methods=['GET'])
def upload_dashboard():
    """Landing page displaying the file upload form."""
    logger.info(f"Upload dashboard accessed by {request.remote_addr}")
    
    html_content = """
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>Quick File Analyzer Pro</title>
        <style>
            :root { --primary: #4f46e5; --bg: #f8fafc; --text: #1e293b; --border: #e2e8f0; }
            body { font-family: system-ui, -apple-system, sans-serif; background-color: var(--bg); color: var(--text); margin: 0; padding: 0; }
            .navbar { background-color: var(--primary); color: white; padding: 1rem 2rem; box-shadow: 0 2px 4px rgba(0,0,0,0.1); }
            .navbar h1 { margin: 0; font-size: 1.5rem; }
            .container { max-width: 800px; margin: 3rem auto; padding: 2rem; background: white; border-radius: 12px; box-shadow: 0 4px 6px -1px rgba(0,0,0,0.1); border: 1px solid var(--border); }
            .upload-area { border: 2px dashed #cbd5e1; border-radius: 8px; padding: 3rem; text-align: center; margin-bottom: 2rem; background-color: #f1f5f9; transition: border-color 0.3s; }
            .upload-area:hover { border-color: var(--primary); }
            .file-input { margin-top: 1rem; }
            .submit-btn { background-color: var(--primary); color: white; border: none; padding: 0.75rem 2rem; border-radius: 6px; font-weight: 600; cursor: pointer; font-size: 1rem; transition: background-color 0.2s; }
            .submit-btn:hover { background-color: #4338ca; }
            .features { display: grid; grid-template-columns: 1fr 1fr 1fr; gap: 1rem; margin-top: 2rem; text-align: center; }
            .feature-card { padding: 1rem; background: #f8fafc; border-radius: 8px; border: 1px solid var(--border); }
        </style>
    </head>
    <body>
        <nav class="navbar">
            <h1>Quick File Analyzer Pro</h1>
        </nav>
        <div class="container">
            <h2 style="margin-top: 0;">Analyze Text Documents Instantly</h2>
            <p style="color: #64748b; margin-bottom: 2rem;">Upload your text file to get instant metrics on word count, character count, and line density.</p>
            
            <form action="/analyze" method="POST" enctype="multipart/form-data">
                <div class="upload-area">
                    <svg width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="#64748b" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                        <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"></path>
                        <polyline points="17 8 12 3 7 8"></polyline>
                        <line x1="12" y1="3" x2="12" y2="15"></line>
                    </svg>
                    <h3>Select a text file to upload</h3>
                    <input type="file" name="document" accept=".txt,.md,.csv" class="file-input" required>
                </div>
                <div style="text-align: right;">
                    <button type="submit" class="submit-btn">Run Analysis &rarr;</button>
                </div>
            </form>

            <div class="features">
                <div class="feature-card"><strong>Fast</strong><br><small>Millisecond processing</small></div>
                <div class="feature-card"><strong>Secure</strong><br><small>No data retained</small></div>
                <div class="feature-card"><strong>Accurate</strong><br><small>Precise metric counts</small></div>
            </div>
        </div>
    </body>
    </html>
    """
    return html_content


@app.route('/analyze', methods=['POST'])
def process_upload():
    """
    VULNERABLE FUNCTION: CWE-79 Cross-Site Scripting (XSS)
    Context: Reflected XSS via Multipart Form-Data Filename.
    
    This function processes an uploaded file and extracts its filename using 
    request.files['document'].filename. It directly embeds this filename into 
    the HTML response without any sanitization or HTML encoding.
    
    Trigger Path:
    1. An attacker constructs a file upload request (multipart/form-data).
    2. They manipulate the 'filename' parameter in the Content-Disposition header 
       to contain a malicious payload (e.g., filename="<img src=x onerror=alert(1)>.txt").
    3. The application reads this malicious filename and reflects it directly into 
       the resulting analysis report page's HTML structure.
    4. The victim's browser executes the injected JavaScript in the context of the app.
    """
    if 'document' not in request.files:
        return "No file part in the request", 400
        
    file = request.files['document']
    
    if file.filename == '':
        return "No file selected for uploading", 400
        
    # Read the file content for analysis
    try:
        content = file.read().decode('utf-8', errors='ignore')
    except Exception as e:
        logger.error(f"Error reading file: {e}")
        return "Failed to process file content.", 500

    # Calculate metrics
    char_count = len(content)
    word_count = len(content.split())
    line_count = len(content.splitlines())
    
    # VULNERABLE SINK: The variable 'file.filename' is concatenated directly into 
    # the HTML string without escaping.
    unsafe_filename = file.filename
    
    logger.info(f"Analyzed file: {unsafe_filename} (Words: {word_count})")

    html_report = f"""
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <title>Analysis Report</title>
        <style>
            :root {{ --primary: #4f46e5; --bg: #f8fafc; --text: #1e293b; --border: #e2e8f0; }}
            body {{ font-family: system-ui, -apple-system, sans-serif; background-color: var(--bg); color: var(--text); margin: 0; padding: 0; }}
            .navbar {{ background-color: var(--primary); color: white; padding: 1rem 2rem; }}
            .container {{ max-width: 800px; margin: 3rem auto; padding: 2rem; background: white; border-radius: 12px; box-shadow: 0 4px 6px -1px rgba(0,0,0,0.1); border: 1px solid var(--border); }}
            .report-header {{ border-bottom: 2px solid var(--border); padding-bottom: 1rem; margin-bottom: 2rem; }}
            .filename-display {{ font-family: monospace; background: #f1f5f9; padding: 0.5rem; border-radius: 4px; color: #b91c1c; font-size: 1.1rem; }}
            .metrics-grid {{ display: grid; grid-template-columns: repeat(3, 1fr); gap: 1.5rem; margin-bottom: 2rem; }}
            .metric-box {{ background: #fff; border: 1px solid var(--
