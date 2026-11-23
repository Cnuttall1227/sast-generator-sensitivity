import os
import csv
import logging
from flask import Flask, request, jsonify, render_template_string

# Configure logging for the Data Analytics Dashboard
logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')
logger = logging.getLogger("DataVizServer")

# Application configuration paths
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATASETS_DIR = os.path.join(BASE_DIR, "datasets")

def initialize_datasets():
    """Ensure the datasets directory exists and populate it with sample CSV files."""
    if not os.path.exists(DATASETS_DIR):
        os.makedirs(DATASETS_DIR)
        
    sample_datasets = {
        "sales_q1.csv": "month,revenue,profit\nJan,10000,2000\nFeb,15000,3500\nMar,12000,2800\n",
        "user_growth.csv": "date,new_users,churn\n2026-01-01,150,12\n2026-02-01,180,15\n2026-03-01,210,10\n",
        "inventory.csv": "item_id,stock,reorder_level\nA123,45,20\nB456,12,50\nC789,120,30\n"
    }
    
    for filename, content in sample_datasets.items():
        filepath = os.path.join(DATASETS_DIR, filename)
        if not os.path.exists(filepath):
            with open(filepath, "w", encoding="utf-8") as f:
                f.write(content)
                
    logger.info(f"Initialized sample data storage at {DATASETS_DIR}")

# Initialize Flask application
app = Flask(__name__)

@app.route('/', methods=['GET'])
def dashboard():
    """Renders the main analytics dashboard HTML page."""
    html_content = """
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>DataViz Pro - Analytics Dashboard</title>
        <style>
            body { font-family: 'Helvetica Neue', Arial, sans-serif; background-color: #f8f9fa; margin: 0; padding: 0; color: #343a40; }
            .navbar { background-color: #343a40; color: white; padding: 15px 30px; font-size: 1.2rem; font-weight: bold; }
            .container { display: flex; max-width: 1200px; margin: 30px auto; gap: 30px; padding: 0 20px; }
            .sidebar { width: 300px; background: white; padding: 20px; border-radius: 8px; box-shadow: 0 2px 4px rgba(0,0,0,0.05); }
            .main-content { flex: 1; background: white; padding: 20px; border-radius: 8px; box-shadow: 0 2px 4px rgba(0,0,0,0.05); min-height: 400px; }
            h2 { margin-top: 0; font-size: 1.1rem; color: #495057; border-bottom: 1px solid #dee2e6; padding-bottom: 10px; }
            .form-group { margin-bottom: 15px; }
            label { display: block; margin-bottom: 5px; font-weight: 500; }
            select { width: 100%; padding: 8px; border: 1px solid #ced4da; border-radius: 4px; }
            button { width: 100%; padding: 10px; background-color: #0d6efd; color: white; border: none; border-radius: 4px; cursor: pointer; font-weight: bold; }
            button:hover { background-color: #0b5ed7; }
            pre { background: #212529; color: #20c997; padding: 15px; border-radius: 6px; overflow-x: auto; white-space: pre-wrap; }
            .error { color: #dc3545; padding: 10px; border: 1px solid #f5c2c7; background-color: #f8d7da; border-radius: 4px; display: none; }
        </style>
    </head>
    <body>
        <div class="navbar">DataViz Pro</div>
        <div class="container">
            <div class="sidebar">
                <h2>Load Dataset</h2>
                <form id="dataForm">
                    <div class="form-group">
                        <label for="dataset_select">Available Sources:</label>
                        <select id="dataset_select" name="dataset_name">
                            <option value="sales_q1.csv">Q1 Sales Data</option>
                            <option value="user_growth.csv">User Growth Metrics</option>
                            <option value="inventory.csv">Current Inventory</option>
                        </select>
                    </div>
                    <button type="submit">Analyze Data</button>
                </form>
            </div>
            <div class="main-content">
                <h2>Data Preview</h2>
                <div id="error-box" class="error"></div>
                <div id="data-view">
                    <p style="color: #6c757d;">Select a dataset from the sidebar to view its raw contents.</p>
                </div>
            </div>
        </div>
        <script>
            document.getElementById('dataForm').addEventListener('submit', async (e) => {
                e.preventDefault();
                const formData = new FormData(e.target);
                const errorBox = document.getElementById('error-box');
                const dataView = document.getElementById('data-view');
                
                errorBox.style.display = 'none';
                dataView.innerHTML = '<p>Loading dataset...</p>';
                
                try {
                    // Send as application/x-www-form-urlencoded
                    const response = await fetch('/api/data/load', {
                        method: 'POST',
                        body: new URLSearchParams(formData)
                    });
                    
                    const result = await response.json();
                    
                    if (response.ok) {
                        dataView.innerHTML = `<pre>${result.data}</pre>`;
                    } else {
                        errorBox.textContent = result.error || 'Failed to load data';
                        errorBox.style.display = 'block';
                        dataView.innerHTML = '';
                    }
                } catch (err) {
                    errorBox.textContent = 'Network error occurred.';
                    errorBox.style.display = 'block';
                }
            });
        </script>
    </body>
    </html>
    """
    return render_template_string(html_content)

import os
from flask import request, jsonify

@app.route('/api/data/load', methods=['POST'])
def load_dataset():
    """
    FIXED: CWE-22 Path Traversal
    Context: Loading raw dataset files for analytics via a Flask POST route.
    
    The 'dataset_name' parameter is now strictly validated to ensure that the resolved 
    absolute path of the requested file remains inside the intended DATASETS_DIR.
    This neutralizes directory traversal sequences like '../' and absolute 
    path injections.
    """
    # Extract the untrusted payload from the URL-encoded POST form data
    target_dataset = request.form.get('dataset_name')
    
    if not target_dataset:
        return jsonify({"error": "Missing 'dataset_name' in form data"}), 400
        
    logger.info(f"Dashboard requested dataset: {target_dataset}")
    
    # FIXED SINK: Secure path resolution to prevent CWE-22
    # 1. Get the absolute path of the intended base directory
    abs_base_dir = os.path.abspath(DATASETS_DIR)
    
    # 2. Construct the requested path and resolve its absolute path
    file_path = os.path.abspath(os.path.join(abs_base_dir, target_dataset))
    
    # 3. Verify the resolved path is strictly within the base directory
    # os.path.commonpath is immune to partial directory name bypasses
    if os.path.commonpath([abs_base_dir, file_path]) != abs_base_dir:
        logger.warning(f"Path traversal attempt blocked: {target_dataset}")
        return jsonify({"error": "Forbidden: Invalid dataset path"}), 403
    
    logger.debug(f"Resolved file path for reading: {file_path}")
    
    try:
        # Safely open and read the file at the validated path
        with open(file_path, "r", encoding="utf-8") as f:
            raw_csv_data = f.read()
            
        return jsonify({
            "status": "success",
            "file": target_dataset,
            "data": raw_csv_data
        }), 200
        
    except FileNotFoundError:
        logger.error(f"Dataset not found at path: {file_path}")
        return jsonify({"error": "The requested dataset does not exist."}), 404
    except PermissionError:
        logger.error(f"Permission denied accessing path: {file_path}")
        return jsonify({"error": "Permission denied accessing the dataset."}), 403
    except Exception as e:
        logger.error(f"Unexpected error while loading {file_path}: {e}")
        return jsonify({"error": "An internal server error occurred."}), 500

if __name__ == "__main__":
    logger.info("Initializing DataViz Pro Environment...")
    initialize_datasets()
    logger.info("Starting Flask Server on port 5000...")
    # Run the Flask development server
    app.run(host="0.0.0.0", port=5000, debug=False)
