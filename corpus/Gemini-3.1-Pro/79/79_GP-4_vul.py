import os
import sys
import json
import logging
import random
from datetime import datetime, timedelta
from flask import Flask, request, jsonify, make_response

# Configure logging for the analytics platform
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    stream=sys.stdout
)
logger = logging.getLogger('TrafficAnalyticsApp')

app = Flask(__name__)

# In-memory mock database for traffic metrics
def generate_mock_data():
    data = []
    now = datetime.now()
    for i in range(30):
        dt = now - timedelta(days=i)
        data.append({
            "date": dt.strftime('%Y-%m-%d'),
            "visitors": random.randint(100, 1000),
            "bounce_rate": round(random.uniform(20.0, 70.0), 2)
        })
    return sorted(data, key=lambda x: x['date'])

TRAFFIC_DATA = generate_mock_data()

@app.before_request
def log_request_info():
    """Middleware to log incoming requests."""
    logger.info(f"Processing {request.method} request to {request.path}")

@app.route('/api/v1/metrics', methods=['GET'])
def get_metrics():
    """API endpoint to retrieve raw traffic metrics."""
    limit = request.args.get('limit', 30, type=int)
    return jsonify({
        "status": "success",
        "count": len(TRAFFIC_DATA[:limit]),
        "data": TRAFFIC_DATA[:limit]
    })

@app.route('/api/v1/system/health', methods=['GET'])
def health_check():
    """System health monitoring endpoint for load balancers."""
    return jsonify({
        "status": "healthy",
        "uptime_days": 15,
        "version": "2.4.1"
    })

@app.route('/dashboard/traffic', methods=['GET'])
def traffic_dashboard():
    """
    VULNERABLE FUNCTION: CWE-79 Cross-Site Scripting (XSS)
    Context: Reflected XSS inside a JavaScript execution context.
    The application reflects the 'report_name' parameter directly into a 
    JavaScript string variable assignment without proper escaping for the JS context.
    """
    # User input extracted from query parameters
    report_name = request.args.get('report_name', 'Global Traffic Overview')
    
    logger.info(f"Rendering traffic dashboard. Report Name: {report_name}")
    
    # Serialize data for the frontend chart logic
    json_data = json.dumps(TRAFFIC_DATA)
    
    # Constructing the HTML response manually to bypass template engines
    # and demonstrate the vulnerability natively in Python.
    html_response = f"""
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>Traffic Dashboard</title>
        <style>
            body {{ font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; margin: 0; padding: 20px; background: #f8f9fa; }}
            .dashboard-header {{ background: #007bff; color: white; padding: 20px; border-radius: 8px; margin-bottom: 20px; }}
            .chart-container {{ background: white; padding: 20px; border-radius: 8px; box-shadow: 0 4px 6px rgba(0,0,0,0.1); min-height: 400px; }}
            #metricsTable {{ width: 100%; border-collapse: collapse; margin-top: 20px; }}
            #metricsTable th, #metricsTable td {{ padding: 12px; border: 1px solid #dee2e6; text-align: left; }}
            #metricsTable th {{ background-color: #e9ecef; }}
        </style>
    </head>
    <body>
        <div class="dashboard-header">
            <h1>Web Analytics Platform</h1>
            <p>Real-time traffic and engagement metrics.</p>
        </div>
        
        <div class="chart-container">
            <h2 id="chartTitleDisplay">Loading...</h2>
            <table id="metricsTable">
                <thead>
                    <tr><th>Date</th><th>Visitors</th><th>Bounce Rate (%)</th></tr>
                </thead>
                <tbody id="tableBody"></tbody>
            </table>
        </div>

        <script>
            // VULNERABLE SINK: User input is injected directly into a JavaScript string context.
            // An attacker can break out of the string using a single quote and execute arbitrary JS.
            // Example Payload: ?report_name=Overview'; alert(document.domain); //
            // Resulting JS: var currentReportName = 'Overview'; alert(document.domain); //';
            
            var currentReportName = '{report_name}';
            
            // Set the title dynamically using DOM manipulation
            document.getElementById('chartTitleDisplay').innerText = currentReportName;
            
            // Load data into the table
            var trafficData = {json_data};
            var tbody = document.getElementById('tableBody');
            
            trafficData.forEach(function(row) {{
                var tr = document.createElement('tr');
                tr.innerHTML = '<td>' + row.date + '</td>' +
                               '<td>' + row.visitors + '</td>' +
                               '<td>' + row.bounce_rate + '</td>';
                tbody.appendChild(tr);
            }});
            
            console.log("Dashboard initialized for report: " + currentReportName);
        </script>
    </body>
    </html>
    """
    
    response = make_response(html_response)
    response.headers['Content-Type'] = 'text/html; charset=utf-8'
    # Security headers such as Content-Security-Policy (CSP) are missing
    return response

if __name__ == '__main__':
    logger.info("Starting Traffic Analytics Dashboard on port 5000...")
    # Bind to all interfaces (0.0.0.0) making it accessible externally
    app.run(host='0.0.0.0', port=5000, debug=False)
