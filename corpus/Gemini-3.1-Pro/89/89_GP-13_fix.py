import argparse
import sqlite3
import os
import sys
import logging
from datetime import datetime
from textwrap import dedent

# Configure logging for the CLI tool
logging.basicConfig(
    level=logging.WARNING,
    format='%(levelname)s: %(message)s'
)
logger = logging.getLogger("NetAssetCLI")

DB_FILE = "infrastructure_inventory.db"

def initialize_database():
    """Initializes the local SQLite database with IT assets and administrative secrets."""
    is_new_db = not os.path.exists(DB_FILE)
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    
    # Create public assets table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS assets (
            asset_id INTEGER PRIMARY KEY AUTOINCREMENT,
            hostname TEXT UNIQUE NOT NULL,
            ip_address TEXT NOT NULL,
            os_version TEXT NOT NULL,
            role TEXT NOT NULL,
            last_seen DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    # Create hidden administrative keys table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS admin_keys (
            key_id INTEGER PRIMARY KEY AUTOINCREMENT,
            service_name TEXT UNIQUE NOT NULL,
            api_key TEXT NOT NULL,
            access_level TEXT NOT NULL
        )
    ''')
    
    if is_new_db:
        # Populate mock assets
        mock_assets = [
            ('web-prod-01', '10.0.5.10', 'Ubuntu 22.04', 'Web Server'),
            ('web-prod-02', '10.0.5.11', 'Ubuntu 22.04', 'Web Server'),
            ('db-prod-01', '10.0.6.50', 'RHEL 8', 'Database'),
            ('db-prod-02', '10.0.6.51', 'RHEL 8', 'Database'),
            ('jumpbox-01', '10.0.1.10', 'Alpine 3.18', 'Bastion Host'),
            ('fw-edge-01', '10.0.0.1', 'pfSense 2.7', 'Firewall')
        ]
        cursor.executemany('''
            INSERT INTO assets (hostname, ip_address, os_version, role)
            VALUES (?, ?, ?, ?)
        ''', mock_assets)
        
        # Populate highly sensitive mock secrets
        mock_secrets = [
            ('AWS_ROOT', 'AKIAIOSFODNN7EXAMPLE', 'SuperAdmin'),
            ('CLOUDFLARE_API', 'c2547eb745079dac9320b638f5e225cf483cc5cf', 'ZoneAdmin'),
            ('DATADOG_AGENT', '9775a026f1ca7d1c6c5af9d94d9595a4', 'MetricsWrite')
        ]
        cursor.executemany('''
            INSERT INTO admin_keys (service_name, api_key, access_level)
            VALUES (?, ?, ?)
        ''', mock_secrets)
        
        conn.commit()
    conn.close()

def display_results(results):
    """Helper function to format and print tabular data to the CLI."""
    if not results:
        print("No assets found matching the criteria.")
        return
        
    print(f"{'Hostname':<15} | {'IP Address':<15} | {'Role':<15}")
    print("-" * 50)
    for row in results:
        print(f"{row[0]:<15} | {row[1]:<15} | {row[2]:<15}")
    print("-" * 50)

def search_assets_by_os(os_name):
    """
    SECURE: Uses parameterized queries (?) to prevent SQL Injection
    """
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    
    # Secure parameterized query
    query = "SELECT hostname, ip_address, role FROM assets WHERE os_version = ?"
    
    try:
        logger.debug(f"Executing secure query for OS: {os_name}")
        # The user input (CLI argument) is passed safely as a tuple parameter
        cursor.execute(query, (os_name,))
        results = cursor.fetchall()
        display_results(results)
    except sqlite3.Error as e:
        # Generic error message prevents error-based data leakage to stderr
        print("A database error occurred while searching for assets.", file=sys.stderr)
    finally:
        conn.close()

def secure_list_all_assets():
    """Securely fetches all assets using a static query."""
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT hostname, ip_address, role FROM assets ORDER BY hostname")
        display_results(cursor.fetchall())
    except sqlite3.Error as e:
        logger.error(f"Database error: {e}")
    finally:
        conn.close()

def main():
    initialize_database()
    
    parser = argparse.ArgumentParser(
        prog="netasset",
        description="CLI tool for managing and querying IT infrastructure assets.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=dedent('''\
            Examples:
              python netasset.py list
              python netasset.py search-os "Ubuntu 22.04"
              
            Exploitation Example (CLI argument injection):
              python netasset.py search-os "Ubuntu 22.04' UNION SELECT service_name, api_key, access_level FROM admin_keys--"
        ''')
    )
    
    subparsers = parser.add_subparsers(dest="command", help="Available commands")
    
    # Command: list
    list_parser = subparsers.add_parser("list", help="List all tracked infrastructure assets")
    
    # Command: search-os
    search_parser = subparsers.add_parser("search-os", help="Search assets by Operating System version")
    search_parser.add_argument("os_version", type=str, help="The exact OS version to filter by")
    
    args = parser.parse_args()
    
    if args.command == "list":
        print("--- All Infrastructure Assets ---")
        secure_list_all_assets()
        
    elif args.command == "search-os":
        print(f"--- Assets running OS: {args.os_version} ---")
        # Triggering the vulnerable function with the parsed command-line argument
        search_assets_by_os(args.os_version)
        
    else:
        parser.print_help()

if __name__ == "__main__":
    main()
