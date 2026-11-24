import csv
import sqlite3
import os
import logging
from datetime import datetime

# Configure logging for the ETL Pipeline
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - ETL_BatchProcessor - %(levelname)s - %(message)s'
)
logger = logging.getLogger("SalesETLPipeline")

DB_FILE = "enterprise_data_warehouse.db"
BATCH_FILE = "incoming_daily_transactions.csv"

def setup_warehouse_database():
    """Initializes the data warehouse with reference tables and analytics tables."""
    if os.path.exists(DB_FILE):
        os.remove(DB_FILE)

    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()

    # Create reference table for regional metadata
    cursor.execute('''
        CREATE TABLE regional_metadata (
            region_id INTEGER PRIMARY KEY AUTOINCREMENT,
            region_code TEXT UNIQUE NOT NULL,
            manager_name TEXT NOT NULL,
            tax_rate REAL NOT NULL,
            internal_budget_code TEXT NOT NULL
        )
    ''')

    # Create fact table for aggregated daily sales
    cursor.execute('''
        CREATE TABLE sales_fact (
            transaction_id INTEGER PRIMARY KEY AUTOINCREMENT,
            transaction_date TEXT NOT NULL,
            region_code TEXT NOT NULL,
            gross_revenue REAL NOT NULL,
            net_revenue REAL NOT NULL
        )
    ''')

    # Populate reference data with highly sensitive internal budget codes
    reference_data = [
        ('NA-EAST', 'Jane Smith', 0.08, 'BUDGET-SEC-881299'),
        ('NA-WEST', 'John Doe', 0.09, 'BUDGET-SEC-992311'),
        ('EU-CENTRAL', 'Hans Gruber', 0.19, 'BUDGET-SEC-100455'),
        ('APAC', 'Mei Lin', 0.12, 'BUDGET-SEC-550122')
    ]
    cursor.executemany('''
        INSERT INTO regional_metadata (region_code, manager_name, tax_rate, internal_budget_code)
        VALUES (?, ?, ?, ?)
    ''', reference_data)

    conn.commit()
    conn.close()
    logger.info("Data warehouse initialized with regional metadata.")

def create_sample_batch_file():
    """Creates a sample CSV file containing the daily sales batch to be processed."""
    headers = ['transaction_date', 'region_code', 'revenue']
    
    # The last row contains a malicious SQL injection payload injected into the 'region_code' column
    rows = [
        ['2023-10-01', 'NA-EAST', '1500.50'],
        ['2023-10-01', 'EU-CENTRAL', '2300.00'],
        ['2023-10-01', 'NA-WEST', '890.25'],
        ['2023-10-01', "APAC' UNION SELECT internal_budget_code FROM regional_metadata WHERE region_code='NA-EAST", '0.00']
    ]

    with open(BATCH_FILE, mode='w', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        writer.writerow(headers)
        writer.writerows(rows)
    logger.info(f"Generated sample batch file: {BATCH_FILE}")

def fetch_region_tax_rate(region_code: str):
    """
    VULNERABLE FUNCTION: CWE-89 SQL Injection
    Trigger Path: File-based data ingestion (parsing CSV column values)
    """
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()

    # Vulnerability: Direct string concatenation of the CSV parsed value into the SQL query
    query = f"SELECT tax_rate FROM regional_metadata WHERE region_code = '{region_code}'"

    try:
        logger.debug(f"Executing metadata lookup query: {query}")
        cursor.execute(query)
        record = cursor.fetchone()

        if record:
            # In an exploitation scenario with UNION, record[0] might contain leaked string data
            return float(record[0])
        return None

    except sqlite3.Error as e:
        logger.error(f"Database error during metadata lookup: {e}")
        # Leaking the DB error into ETL logs, which might be exposed in a monitoring dashboard
        return f"ERROR: {e}"
    except ValueError as ve:
        # If the UNION returns a string (like a budget code) instead of a float, log it
        logger.error(f"Data type conversion error (Possible Data Leakage): Returned value was '{record[0]}'")
        return None
    finally:
        conn.close()

def process_daily_batch(file_path):
    """Reads the CSV file, calculates net revenue, and securely inserts into the data warehouse."""
    if not os.path.exists(file_path):
        logger.error(f"Batch file not found: {file_path}")
        return

    logger.info(f"Starting ETL processing for batch: {file_path}")
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    success_count = 0

    with open(file_path, mode='r', encoding='utf-8') as f:
        reader = csv.DictReader(f)

        for row_num, row in enumerate(reader, start=1):
            tx_date = row.get('transaction_date')
            region = row.get('region_code')
            
            try:
                revenue = float(row.get('revenue', 0))
            except ValueError:
                logger.warning(f"Row {row_num}: Invalid revenue format. Skipping.")
                continue

            # Triggering the vulnerable function using data extracted directly from the CSV file
            tax_rate = fetch_region_tax_rate(region)

            if tax_rate is None or isinstance(tax_rate, str):
                logger.warning(f"Row {row_num}: Invalid or missing region code '{region}'. Skipping.")
                continue

            net_revenue = revenue - (revenue * tax_rate)

            # Secure insertion into the fact table
            try:
                cursor.execute('''
                    INSERT INTO sales_fact (transaction_date, region_code, gross_revenue, net_revenue)
                    VALUES (?, ?, ?, ?)
                ''', (tx_date, region, revenue, net_revenue))
                success_count += 1
            except sqlite3.Error as e:
                logger.error(f"Row {row_num}: Failed to insert fact record: {e}")

    conn.commit()
    conn.close()
    logger.info(f"ETL processing complete. Successfully loaded {success_count} records.")

def run_etl_pipeline():
    """Main execution orchestrator for the ETL process."""
    setup_warehouse_database()
    create_sample_batch_file()
    
    process_daily_batch(BATCH_FILE)
    
    # Cleanup temporary batch files
    if os.path.exists(BATCH_FILE):
        os.remove(BATCH_FILE)
        logger.info("Temporary batch files cleaned up.")

if __name__ == "__main__":
    run_etl_pipeline()
