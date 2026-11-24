import sqlite3
import os
import tkinter as tk
from tkinter import ttk, messagebox

DB_FILE = "library_catalog.db"

def setup_database():
    """Initializes the local SQLite database with a books table and sample data."""
    is_new = not os.path.exists(DB_FILE)
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS books (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            author TEXT NOT NULL,
            genre TEXT,
            published_year INTEGER,
            availability_status TEXT DEFAULT 'Available'
        )
    ''')
    
    if is_new:
        sample_books = [
            ('The Great Gatsby', 'F. Scott Fitzgerald', 'Fiction', 1925, 'Checked Out'),
            ('To Kill a Mockingbird', 'Harper Lee', 'Fiction', 1960, 'Available'),
            ('1984', 'George Orwell', 'Dystopian', 1949, 'Available'),
            ('Brave New World', 'Aldous Huxley', 'Dystopian', 1932, 'Available'),
            ('A Brief History of Time', 'Stephen Hawking', 'Science', 1988, 'Available'),
            ('The Art of Computer Programming', 'Donald Knuth', 'Technology', 1968, 'Reference Only')
        ]
        cursor.executemany('''
            INSERT INTO books (title, author, genre, published_year, availability_status)
            VALUES (?, ?, ?, ?, ?)
        ''', sample_books)
        conn.commit()
    conn.close()

class LibraryDesktopApp:
    def __init__(self, root):
        self.root = root
        self.root.title("Desktop Library Management System")
        self.root.geometry("800x500")
        self.root.configure(padx=20, pady=20)
        
        self.create_widgets()
        self.load_all_books()

    def create_widgets(self):
        # Title
        title_label = tk.Label(self.root, text="Library Search System", font=("Helvetica", 16, "bold"))
        title_label.pack(pady=(0, 15))

        # Search Frame
        search_frame = tk.Frame(self.root)
        search_frame.pack(fill=tk.X, pady=10)

        tk.Label(search_frame, text="Search by Author:").pack(side=tk.LEFT, padx=(0, 10))
        
        self.author_entry = tk.Entry(search_frame, width=40)
        self.author_entry.pack(side=tk.LEFT, padx=(0, 10))
        
        search_btn = tk.Button(search_frame, text="Search", command=self.search_by_author)
        search_btn.pack(side=tk.LEFT)
        
        reset_btn = tk.Button(search_frame, text="Reset", command=self.load_all_books)
        reset_btn.pack(side=tk.LEFT, padx=(10, 0))

        # Results Treeview
        columns = ("ID", "Title", "Author", "Genre", "Year", "Status")
        self.tree = ttk.Treeview(self.root, columns=columns, show="headings", height=15)
        
        for col in columns:
            self.tree.heading(col, text=col)
            self.tree.column(col, width=120)
        
        self.tree.column("ID", width=40)
        self.tree.column("Year", width=60)
        
        self.tree.pack(fill=tk.BOTH, expand=True, pady=10)

    def load_all_books(self):
        """Secure function to load all books initially."""
        self.tree.delete(*self.tree.get_children())
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        try:
            cursor.execute("SELECT * FROM books")
            for row in cursor.fetchall():
                self.tree.insert("", tk.END, values=row)
        except sqlite3.Error as e:
            messagebox.showerror("Database Error", str(e))
        finally:
            conn.close()

    def search_by_author(self):
        """
        VULNERABLE FUNCTION: CWE-89 SQL Injection
        Trigger Path: Desktop GUI application Text Entry widget extraction
        """
        # Clear current treeview results
        self.tree.delete(*self.tree.get_children())
        
        # Extract user input from the Tkinter Entry widget
        author_name = self.author_entry.get()
        
        if not author_name:
            self.load_all_books()
            return
            
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        
        # Vulnerability: Direct string concatenation of GUI input into SQL command
        query = f"SELECT * FROM books WHERE author = '{author_name}'"
        
        try:
            cursor.execute(query)
            results = cursor.fetchall()
            
            if not results:
                messagebox.showinfo("No Results", f"No books found for author: {author_name}")
            else:
                for row in results:
                    self.tree.insert("", tk.END, values=row)
                    
        except sqlite3.Error as e:
            # Displays the syntax error caused by injection to the GUI user
            messagebox.showerror("SQL Execution Error", f"Failed query: {query}\n\nError: {e}")
        finally:
            conn.close()

if __name__ == "__main__":
    setup_database()
    
    # Initialize the Tkinter application
    root = tk.Tk()
    app = LibraryDesktopApp(root)
    
    # To exploit this locally, a user would type the following into the Author search box:
    # ' OR 1=1 --
    # Or to extract hidden schemas:
    # ' UNION SELECT 1, sql, 3, 4, 5, 6 FROM sqlite_master --
    
    root.mainloop()
