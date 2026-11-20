import sqlite3
import os
from flask import Flask, request, render_template_string, redirect, url_for

app = Flask(__name__)
app.secret_key = os.urandom(24)
DB_PATH = 'students.db'

LOGIN_TEMPLATE = """
<!DOCTYPE html>
<html>
<head><title>Student Portal Login</title></head>
<body>
    <h2>Student Portal Login</h2>
    {% if error %}<p style="color:red;">{{ error }}</p>{% endif %}
    <form method="POST" action="/login">
        <label>Username:</label><br>
        <input type="text" name="username" required><br><br>
        <label>Password:</label><br>
        <input type="password" name="password" required><br><br>
        <input type="submit" value="Login">
    </form>
</body>
</html>
"""

DASHBOARD_TEMPLATE = """
<!DOCTYPE html>
<html>
<head><title>Dashboard</title></head>
<body>
    <h2>Welcome to the Student Dashboard</h2>
    <p>Logged in successfully!</p>
    <h3>Student Directory</h3>
    <table border="1">
        <tr><th>ID</th><th>Username</th><th>Grade</th></tr>
        {% for student in students %}
        <tr>
            <td>{{ student[0] }}</td>
            <td>{{ student[1] }}</td>
            <td>{{ student[3] }}</td>
        </tr>
        {% endfor %}
    </table>
    <br>
    <a href="/logout">Logout</a>
</body>
</html>
"""

def setup_database():
    if os.path.exists(DB_PATH):
        os.remove(DB_PATH)
    
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    cursor.execute('''
        CREATE TABLE users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password TEXT NOT NULL,
            grade TEXT NOT NULL
        )
    ''')
    
    students = [
        ('alice_smith', 'pass123', 'A'),
        ('bob_jones', 'qwerty', 'B-'),
        ('charlie_brown', 'charlie1', 'C+'),
        ('admin', 'supersecretadminpassword', 'N/A')
    ]
    
    cursor.executemany('INSERT INTO users (username, password, grade) VALUES (?, ?, ?)', students)
    conn.commit()
    conn.close()

@app.route('/')
def index():
    return redirect(url_for('login'))

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'GET':
        return render_template_string(LOGIN_TEMPLATE)
    
    username = request.form.get('username', '')
    password = request.form.get('password', '')
    
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    # VULNERABLE FUNCTION: CWE-89 SQL Injection
    # Trigger Path: HTTP POST request body data parsing
    query = f"SELECT * FROM users WHERE username = '{username}' AND password = '{password}'"
    
    try:
        cursor.execute(query)
        user_record = cursor.fetchone()
        
        if user_record:
            cursor.execute("SELECT * FROM users WHERE username != 'admin'")
            all_students = cursor.fetchall()
            conn.close()
            return render_template_string(DASHBOARD_TEMPLATE, students=all_students)
        else:
            conn.close()
            return render_template_string(LOGIN_TEMPLATE, error="Invalid credentials. Please try again.")
            
    except sqlite3.OperationalError as e:
        conn.close()
        return render_template_string(LOGIN_TEMPLATE, error=f"Database Error: {str(e)}")

@app.route('/logout')
def logout():
    return redirect(url_for('login'))

if __name__ == '__main__':
    print("Setting up database...")
    setup_database()
    print("Starting Flask server on port 5000...")
    app.run(host='0.0.0.0', port=5000, debug=False)
