import sqlite3

# Connect to your database (it will create one if it doesn't exist)
conn = sqlite3.connect("library.db")
cur = conn.cursor()

# Create users table
cur.execute('''CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT,
    email TEXT UNIQUE,
    password TEXT,
    role TEXT
)''')

# Create books table
cur.execute('''CREATE TABLE IF NOT EXISTS books (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT,
    author TEXT,
    isbn TEXT UNIQUE,
    copies_total INTEGER,
    copies_available INTEGER,
    year INTEGER,
    category TEXT
)''')

# Insert an admin user
cur.execute('''INSERT OR IGNORE INTO users (name, email, password, role)
VALUES (?, ?, ?, ?)''',
("Admin", "admin@example.com", "admin123", "admin"))

# Insert a few sample books
books = [
    ("Python Basics", "John Smith", "9780134685991", 5, 5, 2021, "Programming"),
    ("Data Science Handbook", "Jake VanderPlas", "9781491912058", 3, 3, 2018, "Data Science"),
    ("Machine Learning Guide", "Andrew Ng", "9781789955750", 4, 4, 2020, "AI")
]
cur.executemany('''INSERT OR IGNORE INTO books
(title, author, isbn, copies_total, copies_available, year, category)
VALUES (?, ?, ?, ?, ?, ?, ?)''', books)

conn.commit()
conn.close()

print("✅ Database seeded successfully with admin and sample books!")

