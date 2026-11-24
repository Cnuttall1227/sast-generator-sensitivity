import os
import logging
from http.server import BaseHTTPRequestHandler, HTTPServer

# Configure logging for the application
logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')
logger = logging.getLogger("ThemeServer")

# Application configuration paths
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
THEMES_DIR = os.path.join(BASE_DIR, "themes")

def initialize_themes():
    """Create the themes directory and populate it with default CSS files."""
    if not os.path.exists(THEMES_DIR):
        os.makedirs(THEMES_DIR)
    
    default_themes = {
        "light.css": "body { background: #ffffff; color: #111827; }\n.card { background: #f3f4f6; }",
        "dark.css": "body { background: #111827; color: #ffffff; }\n.card { background: #1f2937; }",
        "hc.css": "body { background: #000000; color: #00ff00; }\n.card { border: 2px solid #00ff00; }"
    }
    
    for filename, content in default_themes.items():
        filepath = os.path.join(THEMES_DIR, filename)
        if not os.path.exists(filepath):
            with open(filepath, "w", encoding="utf-8") as f:
                f.write(content)
                
    logger.info(f"Initialized theme storage at {THEMES_DIR}")

class DynamicThemeHandler(BaseHTTPRequestHandler):
    
    def do_GET(self):
        """Router for incoming GET requests."""
        if self.path == '/':
            self.serve_dashboard()
        elif self.path == '/api/theme/dynamic':
            self.serve_theme_file()
        else:
            self.send_error(404, "Endpoint Not Found")
            
    def serve_dashboard(self):
        """Renders the frontend application interface."""
        html_content = """
        <!DOCTYPE html>
        <html lang="en">
        <head>
            <meta charset="UTF-8">
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
            <title>Dynamic Theme Previewer</title>
            <style>
                /* Base styles before dynamic theme injection */
                body { font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; transition: all 0.3s ease; margin: 0; padding: 40px; }
                .container { max-width: 600px; margin: 0 auto; }
                .card { padding: 30px; border-radius: 12px; box-shadow: 0 4px 6px rgba(0,0,0,0.1); transition: all 0.3s ease; }
                .controls { margin-top: 20px; display: flex; gap: 10px; }
                button { padding: 10px 20px; border: none; border-radius: 6px; cursor: pointer; font-weight: bold; background: #3b82f6; color: white; }
                button:hover { background: #2563eb; }
                .error { color: #dc2626; margin-top: 15px; font-size: 0.9rem; display: none; }
            </style>
            <script>
                async function applyTheme(themeFilename) {
                    const errorEl = document.getElementById('error-msg');
                    errorEl.style.display = 'none';
                    try {
                        // The application uses a custom header to dictate which theme to load
                        const response = await fetch('/api/theme/dynamic', {
                            method: 'GET',
                            headers: {
                                'X-Theme-Filename': themeFilename
                            }
                        });
                        
                        if (!response.ok) {
                            throw new Error(`Server returned ${response.status}: ${response.statusText}`);
                        }
                        
                        const cssContent = await response.text();
                        
                        let styleEl = document.getElementById('dynamic-theme-styles');
                        if (!styleEl) {
                            styleEl = document.createElement('style');
                            styleEl.id = 'dynamic-theme-styles';
                            document.head.appendChild(styleEl);
                        }
                        styleEl.textContent = cssContent;
                    } catch (err) {
                        errorEl.textContent = 'Error loading theme: ' + err.message;
                        errorEl.style.display = 'block';
                    }
                }
            </script>
        </head>
        <body>
            <div class="container">
                <div class="card">
                    <h2>Settings Preferences</h2>
                    <p>Customize your viewing experience by injecting different CSS theme files dynamically from the server.</p>
                    
                    <div class="controls">
                        <button onclick="applyTheme('light.css')">Light Mode</button>
                        <button onclick="applyTheme('dark.css')">Dark Mode</button>
                        <button onclick="applyTheme('hc.css')">High Contrast</button>
                    </div>
                    
                    <div id="error-msg" class="error"></div>
                </div>
            </div>
        </body>
        </html>
        """
        self.send_response(200)
        self.send_header('Content-type', 'text/html')
        self.end_headers()
        self.wfile.write(html_content.encode('utf-8'))
        
    def serve_theme_file(self):
        """
        FIXED: CWE-22 Path Traversal
        Context: Serving dynamic CSS themes based on a custom HTTP header.
        
        The 'X-Theme-Filename' header is now strictly validated to ensure that the resolved 
        absolute path of the requested file remains inside the intended THEMES_DIR.
        This neutralizes directory traversal sequences like '../' and absolute 
        path injections.
        """
        # Extract the untrusted payload from the custom HTTP header
        target_filename = self.headers.get('X-Theme-Filename')
        
        if not target_filename:
            self.send_error(400, "Bad Request: Missing 'X-Theme-Filename' header")
            return
            
        logger.info(f"Client requested theme file via header: {target_filename}")
        
        # FIXED SINK: Secure path resolution to prevent CWE-22
        # 1. Get the absolute path of the intended base directory
        abs_base_dir = os.path.abspath(THEMES_DIR)
        
        # 2. Construct the requested path and resolve its absolute path
        target_path = os.path.abspath(os.path.join(abs_base_dir, target_filename))
        
        # 3. Verify the resolved path is strictly within the base directory
        # os.path.commonpath is immune to partial directory name bypasses
        if os.path.commonpath([abs_base_dir, target_path]) != abs_base_dir:
            logger.warning(f"Path traversal attempt blocked: {target_filename}")
            self.send_error(403, "Forbidden: Invalid theme file path")
            return
        
        try:
            # Safely open and read the file at the validated path
            with open(target_path, 'r', encoding='utf-8') as f:
                theme_content = f.read()
                
            self.send_response(200)
            self.send_header('Content-type', 'text/css')
            self.end_headers()
            
            # Send the safe file contents back to the client
            self.wfile.write(theme_content.encode('utf-8'))
            
        except FileNotFoundError:
            logger.error(f"File not found: {target_path}")
            self.send_error(404, "Theme file not found on server")
        except PermissionError:
            logger.error(f"Permission denied: {target_path}")
            self.send_error(403, "Permission denied accessing theme file")
        except Exception as e:
            logger.error(f"Unexpected error reading {target_path}: {e}")
            self.send_error(500, "Internal server error")
          
def run_server(port=8080):
    """Start the standalone HTTP server."""
    initialize_themes()
    server_address = ('', port)
    httpd = HTTPServer(server_address, DynamicThemeHandler)
    logger.info(f"Theme preview server listening on http://localhost:{port}")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        logger.info("Shutting down server...")
    finally:
        httpd.server_close()

if __name__ == '__main__':
    run_server()
