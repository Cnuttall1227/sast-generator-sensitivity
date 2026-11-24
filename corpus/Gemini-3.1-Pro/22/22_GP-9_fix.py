import os
import logging
from flask import Flask, request, Response

# Configure logging for the Report Generator Service
logging.basicConfig(
    level=logging.INFO, 
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger("ReportServer")

app = Flask(__name__)

# Application configuration paths
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
TEMPLATES_DIR = os.path.join(BASE_DIR, "report_templates")

def initialize_system():
    """Ensure the templates directory exists and populate it with default HTML templates."""
    if not os.path.exists(TEMPLATES_DIR):
        os.makedirs(TEMPLATES_DIR)
    
    default_templates = {
        "monthly_summary.html": "<h2>Monthly Financial Summary</h2><p>Total Revenue: $142,000</p><p>Expenses: $89,500</p>",
        "annual_review.html": "<h2>Annual Performance Review</h2><p>Year-over-Year Growth: 24.5%</p><p>New Client Acquisitions: 1,402</p>",
        "inventory_status.html": "<h2>Warehouse Inventory Status</h2><p>Critical Low Stock: 14 SKUs</p><p>Overstocked: 3 SKUs</p>"
    }
    
    for name, content in default_templates.items():
        path = os.path.join(TEMPLATES_DIR, name)
        if not os.path.exists(path):
            with open(path, "w", encoding="utf-8") as f:
                f.write(content)
                
    logger.info(f"Report templates initialized at {TEMPLATES_DIR}")

@app.route('/', methods=['GET'])
def dashboard():
    """Renders the main frontend dashboard for generating reports."""
    html_content = """
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>Automated Report Engine</title>
        <style>
            body { font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; background: #e9ecef; margin: 0; padding: 40px; }
            .card { background: white; padding: 30px; border-radius: 10px; box-shadow: 0 4px 12px rgba(0,0,0,0.1); max-width: 700px; margin: 0 auto; }
            h1 { color: #343a40; margin-top: 0; }
            .form-group { margin-bottom: 20px; display: flex; gap: 15px; }
            select { flex: 1; padding: 12px; font-size: 16px; border: 1px solid #ced4da; border-radius: 6px; }
            button { background: #4361ee; color: white; border: none; padding: 12px 24px; font-size: 16px; border-radius: 6px; cursor: pointer; font-weight: bold; }
            button:hover { background: #3a0ca3; }
            #output-container { margin-top: 30px; padding: 20px; border: 2px dashed #ced4da; background: #f8f9fa; border-radius: 6px; min-height: 150px; }
            .error { color: #d62828; font-weight: bold; }
        </style>
    </head>
    <body>
        <div class="card">
            <h1>Dynamic Report Generator</h1>
            <p style="color: #6c757d;">Select a layout template to generate the live data report.</p>
            
            <div class="form-group">
                <select id="templateSelector">
                    <option value="monthly_summary.html">Monthly Financial Summary</option>
                    <option value="annual_review.html">Annual Performance Review</option>
                    <option value="inventory_status.html">Warehouse Inventory Status</option>
                </select>
                <button onclick="generateReport()">Render Report</button>
            </div>
            
            <div id="output-container">
                <span style="color: #adb5bd;">Report preview will render here...</span>
            </div>
        </div>

        <script>
            function generateReport() {
                const selectedTemplate = document.getElementById('templateSelector').value;
                const output = document.getElementById('output-container');
                output.innerHTML = '<em>Connecting to reporting engine...</em>';
                
                // The template name is passed to the backend via a custom HTTP Header
                fetch('/api/v1/reports/render', {
                    method: 'GET',
                    headers: {
                        'X-Template-Id': selectedTemplate,
                        'Accept': 'text/html'
                    }
                })
                .then(response => {
                    if (!response.ok) {
                        return response.text().then(text => { throw new Error(text || `HTTP ${response.status}`); });
                    }
                    return response.text();
                })
                .then(html => {
                    output.innerHTML = html;
                })
                .catch(err => {
                    output.innerHTML = `<span class="error">Failed to render report: ${err.message}</span>`;
                });
            }
        </script>
    </body>
    </html>
    """
    return Response(html_content, mimetype='text/html')

# Assuming TEMPLATES_DIR and logger are defined in the broader file scope
# BASE_DIR = os.path.dirname(os.path.abspath(__file__))
# TEMPLATES_DIR = os.path.join(BASE_DIR, "report_templates")
# logger = logging.getLogger("ReportServer")

@app.route('/api/v1/reports/render', methods=['GET'])
def render_report():
    """
    FIXED: CWE-22 Path Traversal
    Context: Loading HTML report templates via a Custom HTTP Header in a Flask application.
    
    The 'X-Template-Id' header is now strictly validated to ensure that the 
    resolved absolute path of the requested template remains inside the 
    intended TEMPLATES_DIR. This neutralizes directory traversal sequences 
    like '../' and absolute path injections.
    """
    # Extract the target template file from the custom HTTP header
    template_filename = request.headers.get('X-Template-Id')
    
    if not template_filename:
        logger.warning("Request rejected: Missing X-Template-Id header")
        return Response("Missing X-Template-Id header required for report generation.", status=400)
        
    logger.info(f"Generating report utilizing template: {template_filename}")
    
    # FIXED SINK: Secure path resolution to prevent CWE-22
    # 1. Get the absolute path of the intended base directory
    abs_base_dir = os.path.abspath(TEMPLATES_DIR)
    
    # 2. Construct the requested path and resolve its absolute path
    target_path = os.path.abspath(os.path.join(abs_base_dir, template_filename))
    
    # 3. Verify the resolved path is strictly within the base directory
    # os.path.commonpath prevents partial directory name bypasses
    if os.path.commonpath([abs_base_dir, target_path]) != abs_base_dir:
        logger.warning(f"Path traversal attempt blocked: {template_filename}")
        return Response("Forbidden: Invalid template path.", status=403)
    
    try:
        # Safely open and read the file at the validated path
        with open(target_path, 'r', encoding='utf-8', errors='ignore') as f:
            raw_template_data = f.read()
            
        # Wrap the raw template (or sensitive file) in the report container
        rendered_html = f"""
        <div class="report-wrapper">
            {raw_template_data}
        </div>
        <hr style="border: 1px solid #dee2e6; margin: 20px 0;">
        <small style="color: #6c757d;">Generated dynamically at request time.</small>
        """
        
        return Response(rendered_html, status=200, mimetype='text/html')
        
    except FileNotFoundError:
        logger.error(f"Template not found: {target_path}")
        return Response("The requested report template could not be found.", status=404)
    except PermissionError:
        logger.error(f"Permission denied accessing template: {target_path}")
        return Response("Permission denied while accessing the template.", status=403)
    except Exception as e:
        logger.error(f"Unexpected error rendering {target_path}: {str(e)}")
        return Response("An internal server error occurred while rendering the report.", status=500)

if __name__ == '__main__':
    initialize_system()
    port = 5000
    logger.info(f"Starting Flask Dynamic Report Engine on http://0.0.0.0:{port}")
    # Run the application
    app.run(host='0.0.0.0', port=port, debug=False)
