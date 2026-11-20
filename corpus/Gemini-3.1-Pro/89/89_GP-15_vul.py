import tkinter as tk
from tkinter import ttk, messagebox
import sqlite3
import os
import logging

# Configure logging for the Desktop Application
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - DesktopGUI - %(levelname)s - %(message)s'
)
logger = logging.getLogger("CorporateDirectoryApp")

DB_FILE = "local_cache_directory.db"

def initialize_local_db():
    """Initializes the local SQLite database cache for offline directory access."""
    is_new = not os.path.exists(DB_FILE)
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    
    # Public directory information
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS directory (
            emp_id INTEGER PRIMARY KEY AUTOINCREMENT,
            first_name TEXT NOT NULL,
            last_name TEXT NOT NULL,
            department TEXT NOT NULL,
            phone_ext TEXT NOT NULL
        )
    ''')
    
    # Highly confidential executive notes (should not be accessible via search)
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS executive_notes (
            note_id INTEGER PRIMARY KEY AUTOINCREMENT,
            target_emp_id INTEGER,
            termination_risk TEXT,
            proposed_severance TEXT,
            private_comments TEXT
        )
    ''')
    
    if is_new:
        logger.info("Initializing new local database cache...")
        
        employees = [
            ('Alice', 'Smith', 'Engineering', 'x4012'),
            ('Bob', 'Jones', 'Marketing', 'x3099'),
            ('Charlie', 'Brown', 'Human Resources', 'x2001'),
            ('Diana', 'Prince', 'Executive', 'x1000'),
            ('Eve', 'Adams', 'Engineering', 'x4055')
        ]
        cursor.executemany('''
            INSERT INTO directory (first_name, last_name, department, phone_ext)
            VALUES (?, ?, ?, ?)
        ''', employees)
        
        notes = [
            (2, 'HIGH', '$15,000', 'Performance improvement plan failed. Prepare offboarding.'),
            (5, 'LOW', 'N/A', 'Flight risk. Consider 15% retention bonus next quarter.')
        ]
        cursor.executemany('''
            INSERT INTO executive_notes (target_emp_id, termination_risk, proposed_severance, private_comments)
            VALUES (?, ?, ?, ?)
        ''', notes)
        
        conn.commit()
    conn.close()

class CorporateDirectoryApp:
    def __init__(self, root):
        self.root = root
        self.root.title("Corporate Offline Directory v2.1")
        self.root.geometry("600x400")
        self.root.resizable(False, False)
        
        self.setup_ui()
        
    def setup_ui(self):
        # Search Frame
        search_frame = ttk.LabelFrame(self.root, text="Search Employee Directory")
        search_frame.pack(padx=10, pady=10, fill="x")
        
        ttk.Label(search_frame, text="Last Name:").grid(row=0, column=0, padx=5, pady=5)
        
        self.search_var = tk.StringVar()
        self.search_entry = ttk.Entry(search_frame, textvariable=self.search_var, width=40)
        self.search_entry.grid(row=0, column=1, padx=5, pady=5)
        
        # Bind the enter key to the search function
        self.search_entry.bind('<Return>', lambda event: self.execute_search())
        
        search_btn = ttk.Button(search_frame, text="Search", command=self.execute_search)
        search_btn.grid(row=0, column=2, padx=5, pady=5)
        
        # Results Frame
        results_frame = ttk.Frame(self.root)
        results_frame.pack(padx=10, pady=5, fill="both", expand=True)
        
        # Setup Treeview for tabular results
        columns = ("first_name", "last_name", "department", "phone_ext")
        self.tree = ttk.Treeview(results_frame, columns=columns, show="headings")
        
        self.tree.heading("first_name", text="First Name")
        self.tree.heading("last_name", text="Last Name")
        self.tree.heading("department", text="Department")
        self.tree.heading("phone_ext", text="Extension")
        
        self.tree.column("first_name", width=120)
        self.tree.column("last_name", width=120)
        self.tree.column("department", width=150)
        self.tree.column("phone_ext", width=100)
        
        scrollbar = ttk.Scrollbar(results_frame, orient=tk.VERTICAL, command=self.tree.yview)
        self.tree.configure(yscroll=scrollbar.set)
        
        self.tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        
        # Status bar
        self.status_var = tk.StringVar()
        self.status_var.set("Ready. Enter a last name to search.")
        status_bar = ttk.Label(self.root, textvariable=self.status_var, relief=tk.SUNKEN, anchor=tk.W)
        status_bar.pack(side=tk.BOTTOM, fill=tk.X)

    def execute_search(self):
        """
        VULNERABLE FUNCTION: CWE-89 SQL Injection
        Trigger Path: Desktop GUI Text Entry Widget (Tkinter Entry.get())
        """
        # The user input is retrieved directly from the GUI widget
        search_term = self.search_var.get()
        
        if not search_term:
            self.status_var.set("Please enter a search term.")
            return
            
        # Clear previous results
        for item in self.tree.get_children():
            self.tree.delete(item)
            
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        
        # Vulnerability: Direct string concatenation of GUI input into the SQL query
        query = f"SELECT first_name, last_name, department, phone_ext FROM directory WHERE last_name = '{search_term}'"
        
        try:
            logger.debug(f"Executing GUI search query: {query}")
            cursor.execute(query)
            records = cursor.fetchall()
            
            if not records:
                self.status_var.set(f"No results found for '{search_term}'.")
            else:
                for row in records:
                    self.tree.insert("", tk.END, values=row)
                self.status_var.set(f"Found {len(records)} record(s).")
                
        except sqlite3.Error as e:
            logger.error(f"Database error during search: {e}")
            # Rendering the database error in a GUI popup enables error-based SQL injection mapping
            messagebox.showerror("Database Error", f"An error occurred while executing the query:\n\n{e}")
            self.status_var.set("Search failed due to an error.")
        finally:
            conn.close()

def main():
    initialize_local_db()
    
    # GUI setup and main loop
    root = tk.Tk()
    app = CorporateDirectoryApp(root)
    
    # Example Malicious Input to type into the Tkinter search box:
    # Smith' UNION SELECT target_emp_id, termination_risk, proposed_severance, private_comments FROM executive_notes--
    
    logger.info("Starting Corporate Directory Desktop Client...")
    root.mainloop()

if __name__ == "__main__":
    main()
