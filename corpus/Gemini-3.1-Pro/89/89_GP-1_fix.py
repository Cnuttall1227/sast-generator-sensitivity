import sqlite3
import uvicorn
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
import logging
from typing import List

app = FastAPI(title="Inventory Management API")
DB_FILE = "inventory.db"

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class Item(BaseModel):
    name: str
    description: str
    quantity: int
    price: float

def init_db():
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS inventory (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            description TEXT,
            quantity INTEGER,
            price REAL
        )
    ''')
    cursor.execute("SELECT COUNT(*) FROM inventory")
    if cursor.fetchone()[0] == 0:
        sample_data = [
            ('Laptop', 'High-end gaming laptop', 10, 1500.00),
            ('Mouse', 'Wireless ergonomic mouse', 50, 25.50),
            ('Keyboard', 'Mechanical keyboard', 30, 85.00),
            ('Monitor', '27-inch 4K monitor', 20, 300.00)
        ]
        cursor.executemany('''
            INSERT INTO inventory (name, description, quantity, price)
            VALUES (?, ?, ?, ?)
        ''', sample_data)
        conn.commit()
    conn.close()

@app.on_event("startup")
def startup_event():
    logger.info("Initializing database...")
    init_db()

@app.get("/items/", response_model=List[dict])
def get_all_items():
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM inventory")
    rows = cursor.fetchall()
    conn.close()
    return [dict(row) for row in rows]

@app.post("/items/")
def add_item(item: Item):
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute('''
        INSERT INTO inventory (name, description, quantity, price)
        VALUES (?, ?, ?, ?)
    ''', (item.name, item.description, item.quantity, item.price))
    conn.commit()
    item_id = cursor.lastrowid
    conn.close()
    return {"message": "Item added successfully", "id": item_id}

@app.get("/items/search/")
def search_items_vulnerable(name: str):
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    # SECURE: Uses parameterized queries (?) to prevent SQL Injection
    query = "SELECT * FROM inventory WHERE name = ?"
    
    try:
        logger.info(f"Executing secure query for item: {name}")
        # The user input is passed as a separate tuple parameter
        cursor.execute(query, (name,)) 
        rows = cursor.fetchall()
        conn.close()
        
        if not rows:
            raise HTTPException(status_code=404, detail="Item not found")
            
        return [dict(row) for row in rows]
        
    except sqlite3.Error as e:
        conn.close()
        logger.error(f"Database error: {e}")
        raise HTTPException(status_code=500, detail="Database error occurred")

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
