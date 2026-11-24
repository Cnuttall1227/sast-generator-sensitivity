import os
import json
import logging
from bottle import Bottle, request, response, run, HTTPError

# Configure application logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s | %(levelname)s | %(message)s')
logger = logging.getLogger("I18nService")

# Define the directory where language translation files are stored
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
LOCALES_DIR = os.path.join(BASE_DIR, "locales")

def init_localization_files():
    """Create the locales directory and populate it with sample JSON translation files."""
    if not os.path.exists(LOCALES_DIR):
        os.makedirs(LOCALES_DIR)
        
    mock_translations = {
        "en-US.json": '{"greeting": "Hello", "farewell": "Goodbye", "status": "Active"}',
        "fr-FR.json": '{"greeting": "Bonjour", "farewell": "Au revoir", "status": "Actif"}',
        "es-ES.json": '{"greeting": "Hola", "farewell": "Adiós", "status": "Activo"}'
    }
    
    for filename, content in mock_translations.items():
        filepath = os.path.join(LOCALES_DIR, filename)
        if not os.path.exists(filepath):
            with open(filepath, "w", encoding="utf-8") as f:
                f.write(content)
                
    logger.info(f"Localization engine initialized at {LOCALES_DIR}")

# Initialize the Bottle web framework application
app = Bottle()

@app.route('/')
def translation_dashboard():
    """Render the main single-page application for the translation tester."""
    html_template = """
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>GlobalReach i18n Tester</title>
        <style>
            :root { --bg: #282c34; --text: #abb2bf; --accent: #61afef; --card: #21252b; }
            body { font-family: 'Consolas', 'Courier New', monospace; background-color: var(--bg); color: var(--text); padding: 40px; margin: 0; }
            .header { text-align: center; margin-bottom: 40px; }
            .header h1 { color: var(--accent); margin: 0; }
            .container { max-width: 700px; margin: 0 auto; background: var(--card); padding: 30px; border-radius: 8px; box-shadow: 0 10px 30px rgba(0,0,0,0.5); }
            .btn-group { display: flex; justify-content: center; gap: 15px; margin-bottom: 30px; }
            .btn { background: transparent; border: 2px solid var(--accent); color: var(--accent); padding: 10px 20px; border-radius: 5px; cursor: pointer; font-weight: bold; font-family: inherit; transition: all 0.3s; }
            .btn:hover { background: var(--accent); color: var(--bg); }
            .output-box { background: #181a1f; border-left: 4px solid #98c379; padding: 20px; border-radius: 4px; min-height: 150px; overflow-x: auto; white-space: pre-wrap; }
            .error { border-left-color: #e06c75; color: #e06c75; }
        </style>
        <script>
            async function loadLanguage(langFile) {
                const outputBox = document.getElementById('output');
                outputBox.className = 'output-box';
                outputBox.textContent = 'Fetching translations...';
                
                try {
                    // The langFile is appended directly to the URL path
                    const response = await fetch(`/api/locales/${langFile}`);
                    const textData = await response.text();
                    
                    if (response.ok) {
                        try {
                            const jsonData = JSON.parse(textData);
                            outputBox.textContent = JSON.stringify(jsonData, null, 4);
                        } catch (e) {
                            // Display raw text if it's not valid JSON
                            outputBox.textContent = textData;
                        }
                    } else {
                        outputBox.className = 'output-box error';
                        outputBox.textContent = `HTTP ${response.status}: ${textData}`;
                    }
                } catch (err) {
                    outputBox.className = 'output-box error';
                    outputBox.textContent = 'Connection error.';
                }
            }
        </script>
    </head>
    <body>
        <div class="header">
            <h1>GlobalReach i18n Tester</h1>
            <p>Test locale payload retrieval via the REST API.</p>
        </div>
        <div class="container">
            <div class="btn-group">
                <button class="btn" onclick="loadLanguage('en-US.json')">English (US)</button>
                <button class="btn" onclick="loadLanguage('fr-FR.json')">French (FR)</button>
                <button class="btn" onclick="loadLanguage('es-ES.json')">Spanish (ES)</button>
            </div>
            
            <div id="output" class="output-box">Select a language to view its JSON payload.</div>
        </div>
    </body>
    </html>
    """
    return html_template

@app.route('/api/locales/<lang_file:path>')
def fetch_translation_payload(lang_file):
    """
    VULNERABLE FUNCTION: CWE-22 Path Traversal
    Context: Serving localization files via a Bottle URL path parameter.
    
    Trigger Path:
    Bottle's '<name:path>' wildcard filter captures everything following the route prefix, 
    including forward slashes. An attacker can craft a malicious HTTP GET request using 
    URL path traversal sequences directly in the URI.
    
    Example exploit request:
    GET /api/locales/../../../../../etc/passwd HTTP/1.1
    
    The 'lang_file' variable will capture '../../../../../etc/passwd'. The os.path.join() 
    function blindly concatenates this with the intended LOCALES_DIR. The application 
    then opens the targeted system file and returns its contents to the attacker.
    """
    logger.info(f"API request for locale file via URI path: {lang_file}")
    
    if not lang_file:
        raise HTTPError(400, "Language file parameter is missing.")
        
    # VULNERABLE SINK: Direct concatenation of untrusted URL path input into a file path.
    # Python's os.path.join resolves directory traversal sequences ('../') and absolute 
    # paths without enforcing boundaries against the base directory.
    target_path = os.path.join(LOCALES_DIR, lang_file)
    
    logger.debug(f"Resolved file path for reading: {target_path}")
    
    try:
        # Blindly open and read the file at the traversed path
        with open(target_path, "r", encoding="utf-8") as f:
            file_contents = f.read()
            
        # Returning contents as JSON, though attackers could retrieve arbitrary text
        response.content_type = 'application/json'
        return file_contents
        
    except FileNotFoundError:
        logger.error(f"Locale file not found at path: {target_path}")
        raise HTTPError(404, "The requested localization file does not exist.")
    except PermissionError:
        logger.error(f"Permission denied accessing path: {target_path}")
        raise HTTPError(403, "Permission denied accessing the localization file.")
    except Exception as e:
        logger.error(f"Unexpected error while loading {target_path}: {e}")
        raise HTTPError(500, "An internal server error occurred.")

if __name__ == '__main__':
    init_localization_files()
    logger.info("Starting Bottle Localization Server on port 8080...")
    # Run the Bottle development server
    run(app, host='0.0.0.0', port=8080, debug=False, quiet=True)
