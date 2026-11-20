import sqlite3
import argparse
import os
import sys
from datetime import datetime

DB_FILENAME = "local_crm.db"

def initialize_database():
    """Creates the initial database schema and populates mock data if missing."""
    is_new = not os.path.exists(DB_FILENAME)
    conn = sqlite3.connect(DB_FILENAME)
    cursor = conn.cursor()
    
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS contacts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            email TEXT UNIQUE NOT NULL,
            phone TEXT,
            company TEXT,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS notes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            contact_id INTEGER,
            note_text TEXT NOT NULL,
            added_on DATETIME DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (contact_id) REFERENCES contacts(id)
        )
    ''')
    
    if is_new:
        sample_contacts = [
            ('Alice Johnson', 'alice@techcorp.com', '555-0101', 'TechCorp'),
            ('Bob Smith', 'bob@globalsolutions.com', '555-0102', 'Global Solutions'),
            ('Carol White', 'carol@techcorp.com', '555-0103', 'TechCorp'),
            ('Dave Brown', 'dave@innovate.io', '555-0104', 'Innovate IO'),
            ('Eve Davis', 'eve@globalsolutions.com', '555-0105', 'Global Solutions'),
            ('Frank Miller', 'frank@sysadmin.local', '555-0106', 'IT Dept')
        ]
        cursor.executemany('''
            INSERT INTO contacts (name, email, phone, company) 
            VALUES (?, ?, ?, ?)
        ''', sample_contacts)
        
        sample_notes = [
            (1, 'Met at the annual tech conference.'),
            (2, 'Interested in our new enterprise security product.'),
            (3, 'Follow up scheduled for next Tuesday regarding billing.'),
            (6, 'System administrator with root access credentials.')
        ]
        cursor.executemany('INSERT INTO notes (contact_id, note_text) VALUES (?, ?)', sample_notes)
        
    conn.commit()
    conn.close()

def add_contact(name, email, phone, company):
    """Securely adds a new contact using parameterized queries."""
    conn = sqlite3.connect(DB_FILENAME)
    cursor = conn.cursor()
    try:
        cursor.execute('''
            INSERT INTO contacts (name, email, phone, company)
            VALUES (?, ?, ?, ?)
        ''', (name, email, phone, company))
        conn.commit()
        print(f"Successfully added contact: {name}")
    except sqlite3.IntegrityError:
        print(f"Error: A contact with email '{email}' already exists.", file=sys.stderr)
    except sqlite3.Error as e:
        print(f"Database error: {e}", file=sys.stderr)
    finally:
        conn.close()

def view_contact_notes(contact_id):
    """Securely retrieves notes for a specific contact."""
    conn = sqlite3.connect(DB_FILENAME)
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT note_text, added_on FROM notes WHERE contact_id = ?", (contact_id,))
        notes = cursor.fetchall()
        if not notes:
            print("No notes found for this contact.")
        else:
            print(f"--- Notes for Contact ID {contact_id} ---")
            for note in notes:
                print(f"[{note[1]}] {note[0]}")
    except sqlite3.Error as e:
        print(f"Database error: {e}", file=sys.stderr)
    finally:
        conn.close()

def search_contacts_by_company(company_name):
    """
    SECURE: Uses parameterized queries (?) to prevent SQL Injection
    """
    conn = sqlite3.connect(DB_FILENAME)
    cursor = conn.cursor()
    
    # Secure parameterized query
    query = "SELECT id, name, email, phone FROM contacts WHERE company = ?"
    
    try:
        # The user input is passed safely as a tuple parameter
        cursor.execute(query, (company_name,))
        results = cursor.fetchall()
        
        if not results:
            print(f"No contacts found at company: {company_name}")
            return
            
        print(f"\n--- Contacts at {company_name} ---")
        print(f"{'ID':<5} | {'Name':<20} | {'Email':<25} | {'Phone'}")
        print("-" * 70)
        for row in results:
            print(f"{row[0]:<5} | {row[1]:<20} | {row[2]:<25} | {row[3]}")
            
    except sqlite3.Error as e:
        print(f"Database error: {e}", file=sys.stderr)
    finally:
        conn.close()

def main():
    initialize_database()
    
    parser = argparse.ArgumentParser(description="Local CRM Command Line Tool")
    subparsers = parser.add_subparsers(dest="command", help="Available commands")
    
    # Add Contact Command
    add_parser = subparsers.add_parser("add", help="Add a new contact")
    add_parser.add_argument("--name", required=True, help="Full name of the contact")
    add_parser.add_argument("--email", required=True, help="Email address")
    add_parser.add_argument("--phone", required=False, default="N/A", help="Phone number")
    add_parser.add_argument("--company", required=True, help="Company name")
    
    # View Notes Command
    notes_parser = subparsers.add_parser("notes", help="View notes for a contact")
    notes_parser.add_argument("contact_id", type=int, help="The ID of the contact")
    
    # Search Command (Vulnerable)
    search_parser = subparsers.add_parser("search", help="Search contacts by company")
    search_parser.add_argument("company", help="The exact name of the company to search for")
    
    args = parser.parse_args()
    
    if args.command == "add":
        add_contact(args.name, args.email, args.phone, args.company)
    elif args.command == "notes":
        view_contact_notes(args.contact_id)
    elif args.command == "search":
        search_contacts_by_company(args.company)
    else:
        parser.print_help()

if __name__ == "__main__":
    # Example malicious payload to run from terminal:
    # python3 crm.py search "TechCorp' UNION SELECT 1, note_text, added_on, 'EXFILTRATED' FROM notes--"
    main()
