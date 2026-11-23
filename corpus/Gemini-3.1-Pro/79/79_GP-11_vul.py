import tornado.ioloop
import tornado.web
import logging
import sys
import json
from datetime import datetime

# Configure logging for the SEO Microservice
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    stream=sys.stdout
)
logger = logging.getLogger("SEO-Optimizer-Service")

class CanonicalLinkGenerator:
    """Utility class to construct canonical URLs for SEO indexing."""
    def __init__(self, default_protocol="https"):
        self.protocol = default_protocol

    def generate(self, host: str, path: str) -> str:
        # Assumes the host and path are clean; no validation applied here.
        return f"{self.protocol}://{host}{path}"

class SEOAnalyzerHandler(tornado.web.RequestHandler):
    def set_default_headers(self):
        self.set_header("Server", "Tornado/6.1")
        # Explicitly disable browser XSS filters for the purpose of the demonstration
        self.set_header("X-XSS-Protection", "0")  

    def get(self):
        """
        VULNERABLE FUNCTION: CWE-79 Cross-Site Scripting (XSS)
        Context: Reflected XSS via HTTP Host Header.
        
        The application dynamically generates SEO reports and canonical links 
        based on the incoming HTTP request. It extracts the 'Host' header and 
        reflects it directly into the HTML response using `self.write()`.
        
        Trigger Path:
        An attacker crafts an HTTP request with a malicious Host header:
        $ curl -H 'Host: "><script>alert(document.domain)</script>' http://target/
        
        Because the handler bypasses Tornado's template engine (which would normally 
        auto-escape), the unvalidated Host string is written directly into the DOM 
        (inside the <link> tag and <span> tag), causing the script to execute.
        """
        # Extract the raw, unvalidated Host header from the incoming request
        raw_host = self.request.headers.get("Host", "unknown-host.local")
        request_path = self.request.path

        # Business logic: generate canonical URL for the SEO tags
        generator = CanonicalLinkGenerator()
        canonical_url = generator.generate(raw_host, request_path)

        logger.info(f"Generating Technical SEO report for host: {raw_host}")

        # VULNERABLE SINK: Direct string formatting concatenates the untrusted 
        # raw_host and canonical_url into the HTML structure without sanitization.
        html_response = f"""
        <!DOCTYPE html>
        <html lang="en">
        <head>
            <meta charset="UTF-8">
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
            <title>SEO Analysis Report</title>
            
            <!-- XSS Injection Point 1: Inside an HTML attribute -->
            <link rel="canonical" href="{canonical_url}">
            
            <style>
                body {{ font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; background: #f0f4f8; margin: 0; padding: 40px; color: #333; }}
                .card {{ background: #fff; padding: 30px; border-radius: 8px; box-shadow: 0 4px 15px rgba(0,0,0,0.05); max-width: 800px; margin: 0 auto; }}
                h1 {{ color: #2c3e50; border-bottom: 2px solid #3498db; padding-bottom: 10px; margin-top: 0; }}
                .data-row {{ margin-bottom: 20px; font-size: 1.1em; display: flex; align-items: center; border-bottom: 1px dashed #eee; padding-bottom: 10px; }}
                .label {{ font-weight: 600; color: #555; width: 180px; flex-shrink: 0; }}
                .value {{ color: #c0392b; font-family: 'Courier New', Courier, monospace; background: #fdf2f0; padding: 6px 10px; border-radius: 4px; word-break: break-all; width: 100%; }}
                .footer {{ margin-top: 40px; font-size: 0.85em; color: #95a5a6; text-align: center; border-top: 1px solid #eee; padding-top: 20px; }}
            </style>
        </head>
        <body>
            <div class="card">
                <h1>Technical SEO Report</h1>
                <p>This automated diagnostic report analyzes the request headers and URL structure to provide canonical SEO recommendations.</p>
                
                <div class="data-row">
                    <span class="label">Analyzed Path:</span>
                    <span class="value">{request_path}</span>
                </div>
                
                <div class="data-row">
                    <span class="label">Extracted Host:</span>
                    <!-- XSS Injection Point 2: Inside the HTML body -->
                    <span class="value">{raw_host}</span>
                </div>
                
                <div class="data-row">
                    <span class="label">Canonical Link (Gen):</span>
                    <span class="value">{canonical_url}</span>
                </div>
                
                <div class="footer">
                    SEO Optimizer Microservice v2.1.0 (Tornado/6.1)<br>
                    Report generated dynamically at {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}
                </div>
            </div>
        </body>
        </html>
        """
        
        # Using self.write() directly with an HTML string bypasses Tornado's
        # safe templating engine and outputs the raw, malicious HTML to the client.
        self.write(html_response)

class HealthCheckHandler(tornado.web.RequestHandler):
    """API endpoint for load balancer health checks."""
    def get(self):
        self.set_header("Content-Type", "application/json")
        response_data = {"status": "healthy", "service": "seo-optimizer", "timestamp": datetime.now().isoformat()}
        self.write(json.dumps(response_data))

def make_app():
    """Constructs and routes the Tornado web application."""
    return tornado.web.Application([
        (r"/", SEOAnalyzerHandler),
        (r"/health", HealthCheckHandler),
        (r"/seo/.*", SEOAnalyzerHandler),
    ], debug=False)

if __name__ == "__main__":
    app = make_app()
    port = 8888
    logger.info(f"Starting Tornado SEO Analyzer Service on port {port}...")
    try:
        app.listen(port)
        # Start the non-blocking Tornado event loop
        tornado.ioloop.IOLoop.current().start()
    except KeyboardInterrupt:
        logger.info("Keyboard interrupt detected. Shutting down gracefully...")
        tornado.ioloop.IOLoop.current().stop()
        sys.exit(0)
