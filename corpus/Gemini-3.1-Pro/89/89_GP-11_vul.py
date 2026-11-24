import sqlite3
import os
import logging
from typing import List, Optional
from fastapi import FastAPI, HTTPException, Query, status
from pydantic import BaseModel
import uvicorn

# Configure logging for the E-Commerce API
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("EcommerceAPI")

DB_FILE = "ecommerce_catalog.db"

def setup_database():
    """Initializes the database with product catalog and internal promotions."""
    if os.path.exists(DB_FILE):
        os.remove(DB_FILE)
        
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    
    # Create products table
    cursor.execute('''
        CREATE TABLE products (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            price REAL NOT NULL,
            category TEXT NOT NULL,
            stock INTEGER DEFAULT 0
        )
    ''')
    
    # Create internal promotions table (hidden from public API)
    cursor.execute('''
        CREATE TABLE internal_promotions (
            promo_id INTEGER PRIMARY KEY AUTOINCREMENT,
            campaign_name TEXT NOT NULL,
            discount_code TEXT UNIQUE NOT NULL,
            discount_percent INTEGER NOT NULL
        )
    ''')
    
    # Insert mock product data
    mock_products = [
        ('Wireless Mouse', 25.99, 'Electronics', 150),
        ('Mechanical Keyboard', 89.99, 'Electronics', 45),
        ('Ergonomic Chair', 199.50, 'Furniture', 12),
        ('Standing Desk', 349.00, 'Furniture', 8),
        ('Coffee Beans 1lb', 14.99, 'Groceries', 200),
        ('Green Tea 50ct', 9.50, 'Groceries', 85)
    ]
    
    cursor.executemany('''
        INSERT INTO products (name, price, category, stock)
        VALUES (?, ?, ?, ?)
    ''', mock_products)
    
    # Insert secret discount codes
    cursor.executemany('''
        INSERT INTO internal_promotions (campaign_name, discount_code, discount_percent)
        VALUES (?, ?, ?)
    ''', [
        ('Black Friday VIP', 'BF_VIP_882910', 40),
        ('Employee Discount', 'EMP_DISC_55912', 50)
    ])
    
    conn.commit()
    conn.close()
    logger.info("E-Commerce database initialized with mock data.")

# Pydantic models for request validation
class ProductCreate(BaseModel):
    name: str
    price: float
    category: str
    stock: int

class ProductResponse(BaseModel):
    id: int
    name: str
    price: float
    stock: int

app = FastAPI(
    title="E-Commerce Product API",
    description="Public API for fetching available products.",
    version="1.0.0"
)

@app.on_event("startup")
def on_startup():
    setup_database()

def get_products_by_category(category_name: str) -> List[dict]:
    """
    VULNERABLE FUNCTION: CWE-89 SQL Injection
    Trigger Path: FastAPI HTTP GET Query Parameter parsing
    """
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    
    # Vulnerability: Direct string concatenation of the HTTP query parameter into the SQL query
    query = f"SELECT id, name, price, stock FROM products WHERE category = '{category_name}' AND stock > 0"
    
    try:
        logger.info(f"Executing database query: {query}")
        cursor.execute(query)
        records = cursor.fetchall()
        
        results = []
        for row in records:
            results.append({
                "id": row[0],
                "name": row[1],
                "price": row[2],
                "stock": row[3]
            })
        return results
        
    except sqlite3.Error as e:
        logger.error(f"Database error in get_products_by_category: {e}")
        # Leaking the database error in the HTTP response enables error-based SQL injection
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Database execution failed: {e}"
        )
    finally:
        conn.close()

def add_new_product(product: ProductCreate):
    """Securely inserts a new product using parameterized queries."""
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    try:
        cursor.execute('''
            INSERT INTO products (name, price, category, stock)
            VALUES (?, ?, ?, ?)
        ''', (product.name, product.price, product.category, product.stock))
        conn.commit()
        return cursor.lastrowid
    except sqlite3.Error as e:
        logger.error(f"Failed to insert product: {e}")
        raise HTTPException(status_code=500, detail="Failed to create product")
    finally:
        conn.close()

@app.get("/api/v1/products/search", response_model=dict)
def search_products(category: str = Query(..., description="The product category to search for")):
    """
    API endpoint to search for available products by category.
    The 'category' parameter is extracted directly from the HTTP request URL.
    """
    products = get_products_by_category(category)
    
    if not products:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, 
            detail=f"No products found in category: {category}"
        )
        
    return {
        "status": "success",
        "category": category,
        "count": len(products),
        "data": products
    }

@app.post("/api/v1/products", status_code=status.HTTP_201_CREATED)
def create_product(product: ProductCreate):
    """API endpoint to securely add a new product to the catalog."""
    new_id = add_new_product(product)
    return {"status": "success", "message": f"Product created with ID {new_id}"}

@app.get("/api/v1/health")
def health_check():
    """Basic health check endpoint."""
    return {"status": "healthy", "service": "E-Commerce API"}

if __name__ == "__main__":
    # Example Malicious HTTP GET Request to exploit this API:
    # curl -X GET "http://127.0.0.1:8000/api/v1/products/search?category=Electronics'%20UNION%20SELECT%20promo_id,%20campaign_name,%20discount_percent,%20discount_code%20FROM%20internal_promotions--"
    
    logger.info("Starting E-Commerce API Server on http://127.0.0.1:8000")
    uvicorn.run(app, host="127.0.0.1", port=8000, log_level="info")
