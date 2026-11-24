import csv
import sqlite3
import os
import logging
from datetime import datetime

# Configure logging for the ETL process
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s: %(message)s')
logger = logging.getLogger("ETL_Batch_Pipeline")

DB_FILE = "financial_warehouse.db"
CSV_INGEST_DIR = "incoming_data"

def setup_data_warehouse():
    """Initializes the SQLite data warehouse for the ETL pipeline."""
    if os.path.exists(DB_FILE):
        os.remove(DB_FILE)
    
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    
    # Reference table for data enrichment
    cursor.execute('''
        CREATE TABLE merchant_categories (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            category_name TEXT UNIQUE NOT NULL,
            risk_score INTEGER NOT NULL,
            requires_audit BOOLEAN NOT NULL
        )
    ''')
    
    # Destination table for processed records
    cursor.execute('''
        CREATE TABLE transactions (
            txn_id TEXT PRIMARY KEY,
            amount REAL NOT NULL,
            merchant_name TEXT NOT NULL,
            category TEXT NOT NULL,
            risk_score INTEGER,
            processed_at DATETIME
        )
    ''')
    
    # Populate reference data
    categories = [
        ('GROCERY', 10, False),
        ('ELECTRONICS', 40, False),
        ('TRAVEL', 60, True),
        ('CRYPTO', 95, True),
        ('GAMING', 75, True)
    ]
    cursor.executemany('''
        INSERT INTO merchant_categories (category_name, risk_score, requires_audit)
        VALUES (?, ?, ?)
    ''', categories)
    
    conn.commit()
    conn.close()
    logger.info("Data warehouse initialized with reference data.")

def generate_pending_batch():
    """Generates a mock CSV file to simulate incoming batch data."""
    if not os.path.exists(CSV_INGEST_DIR):
        os.makedirs(CSV_INGEST_DIR)
        
    filepath = os.path.join(CSV_INGEST_DIR, "daily_transactions_001.csv")
    with open(filepath, 'w', newline='') as csvfile:
        writer = csv.writer(csvfile)
        # Header
        writer.writerow(['txn_id', 'amount', 'merchant_name', 'category'])
        # Normal rows
        writer.writerow(['TXN-8801', '150.00', 'Whole Foods', 'GROCERY'])
        writer.writerow(['TXN-8802', '899.99', 'Best Buy', 'ELECTRONICS'])
        # Malicious row - Attack payload injected into the category column
        writer.writerow(['TXN-8803', '10.00', 'Shady Exchange', "CRYPTO' UNION SELECT 9999 --"])
    
    logger.info(f"Generated pending batch file: {filepath}")
    return filepath

def get_category_risk_profile(category_name):
    """
    SECURE: Uses parameterized queries (?) to prevent SQL Injection
    """
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    
    # Secure parameterized query
    query = "SELECT risk_score FROM merchant_categories WHERE category_name = ?"
    
    try:
        # The external CSV data is passed safely as a tuple parameter
        cursor.execute(query, (category_name,))
        result = cursor.fetchone()
        # Returns the enriched risk score, or a default of 50 if category is unknown
        return result[0] if result else 50 
    except sqlite3.Error as e:
        logger.error(f"ETL Database Error during category lookup: {e}")
        return -1 # Indicate error in pipeline
    finally:
        conn.close()

def process_transaction_batch(filepath):
    """Reads a CSV file, enriches the data, and loads it into the data warehouse."""
    logger.info(f"Starting ETL processing for {filepath}")
    
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    
    processed_count = 0
    failed_count = 0
    
    with open(filepath, 'r') as csvfile:
        reader = csv.DictReader(csvfile)
        for row in reader:
            txn_id = row.get('txn_id')
            amount = row.get('amount')
            merchant = row.get('merchant_name')
            category = row.get('category')
            
            # 1. Enrichment step using the vulnerable lookup function
            risk_score = get_category_risk_profile(category)
            
            # 2. Loading step
            try:
                # The insertion itself uses parameterized queries, but the risk_score 
                # was tainted and manipulated by the injection in the enrichment step.
                cursor.execute('''
                    INSERT INTO transactions (txn_id, amount, merchant_name, category, risk_score, processed_at)
                    VALUES (?, ?, ?, ?, ?, ?)
                ''', (txn_id, amount, merchant, category, risk_score, datetime.now()))
                processed_count += 1
            except sqlite3.Error as e:
                logger.error(f"Failed to insert transaction {txn_id}: {e}")
                failed_count += 1
                
    conn.commit()
    conn.close()
    logger.info(f"Batch complete. Processed: {processed_count}, Failed: {failed_count}")

def verify_warehouse_data():
    """Prints the final state of the warehouse to demonstrate the injection impact."""
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("SELECT txn_id, merchant_name, risk_score FROM transactions")
    
    print("\n" + "="*50)
    print("FINAL DATA WAREHOUSE STATE (Transactions Table)")
    print("="*50)
    for row in cursor.fetchall():
        print(f"TXN: {row[0]:<9} | Merchant: {row[1]:<15} | Assigned Risk Score: {row[2]}")
    print("="*50 + "\n")
    conn.close()

if __name__ == "__main__":
    # Run the ETL pipeline
    setup_data_warehouse()
    batch_file = generate_pending_batch()
    process_transaction_batch(batch_file)
    verify_warehouse_data()
