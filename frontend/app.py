import time
import streamlit as st

st.title("Cloud-Based Library Management System")
st.write("Welcome to your digital library portal!")

import streamlit as st
import sqlite3
import hashlib
import pandas as pd
from datetime import datetime, timedelta
from pathlib import Path

DB_PATH = Path(__file__).parent / "library.db"

# ---------- DB helpers ----------
def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_conn()
    cur = conn.cursor()
    # users table
    cur.execute("""
    CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT,
        email TEXT UNIQUE,
        password_hash TEXT,
        role TEXT DEFAULT 'patron',
        created_at TEXT
    )
    """)
    # books table
    cur.execute("""
    CREATE TABLE IF NOT EXISTS books (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        title TEXT,
        author TEXT,
        isbn TEXT UNIQUE,
        copies_total INTEGER DEFAULT 1,
        copies_available INTEGER DEFAULT 1,
        year INTEGER,
        category TEXT,
        created_at TEXT
    )
    """)
    # loans
    cur.execute("""
    CREATE TABLE IF NOT EXISTS loans (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        book_id INTEGER,
        issue_date TEXT,
        due_date TEXT,
        return_date TEXT,
        fine REAL DEFAULT 0,
        status TEXT DEFAULT 'issued',
        FOREIGN KEY(user_id) REFERENCES users(id),
        FOREIGN KEY(book_id) REFERENCES books(id)
    )
    """)
    conn.commit()
    conn.close()

def create_sample_admin():
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT COUNT(1) as c FROM users")
    if cur.fetchone()["c"] == 0:
        # create admin user
        pw = hash_password("admin123")
        cur.execute("INSERT INTO users (name,email,password_hash,role,created_at) VALUES (?, ?, ?, ?, ?)",
                    ("Admin", "admin@example.com", pw, "admin", datetime.utcnow().isoformat()))
        conn.commit()
    conn.close()

# ---------- auth ----------
def hash_password(password: str):
    return hashlib.sha256(password.encode("utf-8")).hexdigest()

def register_user(name, email, password, role="patron"):
    conn = get_conn()
    cur = conn.cursor()
    try:
        cur.execute("INSERT INTO users (name,email,password_hash,role,created_at) VALUES (?, ?, ?, ?, ?)",
                    (name, email.lower(), hash_password(password), role, datetime.utcnow().isoformat()))
        conn.commit()
        return True, "Registered successfully."
    except sqlite3.IntegrityError as e:
        return False, "Email already exists."
    finally:
        conn.close()

def authenticate(email, password):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT * FROM users WHERE email = ?", (email.lower(),))
    row = cur.fetchone()
    conn.close()
    if row and row["password_hash"] == hash_password(password):
        return dict(row)
    return None

# ---------- book operations ----------
def add_book(title, author, isbn, copies, year, category):
    conn = get_conn()
    cur = conn.cursor()
    try:
        cur.execute("""INSERT INTO books (title,author,isbn,copies_total,copies_available,year,category,created_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                    (title, author, isbn, copies, copies, year, category, datetime.utcnow().isoformat()))
        conn.commit()
        return True, "Book added."
    except sqlite3.IntegrityError:
        return False, "ISBN already exists."
    finally:
        conn.close()

def update_book(book_id, title, author, isbn, copies_total, year, category):
    conn = get_conn()
    cur = conn.cursor()
    # adjust available if total changed (simplest: recalc available = max(0, available + (new_total - old_total)))
    cur.execute("SELECT copies_total, copies_available FROM books WHERE id = ?", (book_id,))
    row = cur.fetchone()
    if not row:
        conn.close()
        return False, "Book not found."
    old_total = row["copies_total"]
    old_available = row["copies_available"]
    delta = copies_total - old_total
    new_available = max(0, old_available + delta)
    cur.execute("""UPDATE books SET title=?, author=?, isbn=?, copies_total=?, copies_available=?, year=?, category=? WHERE id=?""",
                (title, author, isbn, copies_total, new_available, year, category, book_id))
    conn.commit()
    conn.close()
    return True, "Book updated."

def delete_book(book_id):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("DELETE FROM books WHERE id = ?", (book_id,))
    conn.commit()
    conn.close()
    return True

def search_books(query="", category="", only_available=False):
    conn = get_conn()
    cur = conn.cursor()
    q = "SELECT * FROM books WHERE 1=1"
    params = []
    if query:
        q += " AND (title LIKE ? OR author LIKE ? OR isbn LIKE ?)"
        like = f"%{query}%"
        params += [like, like, like]
    if category:
        q += " AND category = ?"
        params.append(category)
    if only_available:
        q += " AND copies_available > 0"
    cur.execute(q, params)
    rows = [dict(r) for r in cur.fetchall()]
    conn.close()
    return rows

# ---------- loan operations ----------
LOAN_DAYS = 14
FINE_PER_DAY = 1.0  # simple fine rate

def issue_book(user_id, book_id):
    conn = get_conn()
    cur = conn.cursor()
    # check availability
    cur.execute("SELECT copies_available FROM books WHERE id = ?", (book_id,))
    row = cur.fetchone()
    if not row or row["copies_available"] <= 0:
        conn.close()
        return False, "No copies available."
    issue_date = datetime.utcnow()
    due_date = issue_date + timedelta(days=LOAN_DAYS)
    cur.execute("INSERT INTO loans (user_id, book_id, issue_date, due_date, status) VALUES (?, ?, ?, ?, ?)",
                (user_id, book_id, issue_date.isoformat(), due_date.isoformat(), "issued"))
    cur.execute("UPDATE books SET copies_available = copies_available - 1 WHERE id = ?", (book_id,))
    conn.commit()
    conn.close()
    return True, "Book issued."

def return_book(loan_id):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT * FROM loans WHERE id = ?", (loan_id,))
    loan = cur.fetchone()
    if not loan:
        conn.close()
        return False, "Loan not found."
    if loan["status"] != "issued":
        conn.close()
        return False, "Book already returned."
    now = datetime.utcnow()
    due = datetime.fromisoformat(loan["due_date"])
    days_late = (now - due).days
    fine = float(days_late * FINE_PER_DAY) if days_late > 0 else 0.0
    cur.execute("UPDATE loans SET return_date=?, fine=?, status=? WHERE id=?",
                (now.isoformat(), fine, "returned", loan_id))
    cur.execute("UPDATE books SET copies_available = copies_available + 1 WHERE id = ?", (loan["book_id"],))
    conn.commit()
    conn.close()
    return True, f"Book returned. Fine: ${fine:.2f}"

def get_user_loans(user_id):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""SELECT loans.*, books.title, books.author FROM loans
                   JOIN books ON loans.book_id = books.id
                   WHERE loans.user_id = ? ORDER BY loans.issue_date DESC""", (user_id,))
    rows = [dict(r) for r in cur.fetchall()]
    conn.close()
    return rows

def get_all_books_df():
    rows = search_books()
    return pd.DataFrame(rows)

# ---------- Streamlit UI ----------
st.set_page_config(page_title="Cloud Library System", layout="wide")
init_db()
create_sample_admin()

# session
if "user" not in st.session_state:
    st.session_state.user = None

st.title("📚 Cloud-Based Library Management System (Demo)")

# Sidebar: auth + navigation
with st.sidebar:
    st.header("Account")
    if st.session_state.user:
        st.info(f"Logged in as {st.session_state.user['name']} ({st.session_state.user['role']})")
        if st.button("Logout"):
            st.session_state.user = None
            st.experimental_rerun()
    else:
        tab = st.radio("Have an account?", ("Login", "Register"))
        if tab == "Login":
            email = st.text_input("Email", key="login_email")
            password = st.text_input("Password", type="password", key="login_pw")
            if st.button("Login"):
                user = authenticate(email, password)
                if user:
                    st.session_state.user = user
                    st.success("Logged in")
                    st.experimental_rerun()
                else:
                    st.error("Invalid credentials")
        else:
            name = st.text_input("Full name", key="reg_name")
            email = st.text_input("Email", key="reg_email")
            password = st.text_input("Password", type="password", key="reg_pw")
            role = st.selectbox("Role", ["patron", "librarian"], key="reg_role")
            if st.button("Register"):
                ok, msg = register_user(name, email, password, role)
                if ok:
                    st.success(msg + " You can now login.")
                else:
                    st.error(msg)

    st.markdown("---")
    st.header("Navigation")
    pages = ["Dashboard", "Catalog", "My Loans"]
    if st.session_state.user and st.session_state.user["role"] in ("librarian", "admin"):
        pages += ["Manage Books"]
    page = st.radio("Go to", pages)

# Main content
if page == "Dashboard":
    st.subheader("Overview")
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) as c FROM books"); books_count = cur.fetchone()["c"]
    cur.execute("SELECT COUNT(*) as c FROM users"); users_count = cur.fetchone()["c"]
    cur.execute("SELECT COUNT(*) as c FROM loans WHERE status='issued'"); issued_count = cur.fetchone()["c"]
    conn.close()
    c1, c2, c3 = st.columns(3)
    c1.metric("Books", books_count)
    c2.metric("Users", users_count)
    c3.metric("Books Issued", issued_count)
    st.markdown("### Recent books")
    df = get_all_books_df()
    if not df.empty:
        st.dataframe(df.head(20))
    else:
        st.write("No books yet. Add some from Manage Books.")

elif page == "Catalog":
    st.subheader("Book Catalog")
    q = st.text_input("Search by title, author, ISBN")
    cat = st.text_input("Filter by category (optional)")
    only_avail = st.checkbox("Only available")
    results = search_books(q, cat, only_avail)
    st.write(f"Found {len(results)} books")
    if results:
        for b in results:
            with st.expander(f"{b['title']} — {b['author']} (Available: {b['copies_available']})"):
                st.write(f"ISBN: {b['isbn']}")
                st.write(f"Year: {b.get('year')}, Category: {b.get('category')}")
                if st.session_state.user:
                    col1, col2 = st.columns([1,3])
                    with col1:
                        if b["copies_available"] > 0:
                            if st.button("Borrow", key=f"borrow_{b['id']}"):
                                ok, msg = issue_book(st.session_state.user["id"], b["id"])
                                if ok:
                                    st.success(msg)
                                    st.experimental_rerun()
                                else:
                                    st.error(msg)
                        else:
                            st.info("No copies available")
                    with col2:
                        st.write("")

elif page == "My Loans":
    if not st.session_state.user:
        st.warning("Please login to view your loans.")
    else:
        st.subheader("Your Loans")
        loans = get_user_loans(st.session_state.user["id"])
        if not loans:
            st.write("No loans found.")
        else:
            for ln in loans:
                issued = datetime.fromisoformat(ln["issue_date"])
                due = datetime.fromisoformat(ln["due_date"])
                status = ln["status"]
                fine = ln["fine"]
                with st.expander(f"{ln['title']} — {ln['author']} ({status})"):
                    st.write(f"Issued: {issued.date()} | Due: {due.date()}")
                    if status == "issued":
                        if st.button("Return", key=f"return_{ln['id']}"):
                            ok, msg = return_book(ln["id"])
                            if ok:
                                st.success(msg)
                                st.experimental_rerun()
                            else:
                                st.error(msg)
                    if status == "returned":
                        st.write(f"Returned on: {ln['return_date']}. Fine: ${fine:.2f}")

elif page == "Manage Books":
    if not st.session_state.user or st.session_state.user["role"] not in ("librarian", "admin"):
        st.error("Access denied.")
    else:
        st.subheader("Manage Books")
        mode = st.radio("Mode", ["Add Book", "Edit / Delete Book", "Bulk Upload (CSV sample)"])
        if mode == "Add Book":
            with st.form("add_book_form"):
                title = st.text_input("Title")
                author = st.text_input("Author")
                isbn = st.text_input("ISBN")
                copies = st.number_input("Copies", value=1, min_value=1)
                year = st.number_input("Year", value=datetime.utcnow().year)
                category = st.text_input("Category")
                submitted = st.form_submit_button("Add Book")
                if submitted:
                    ok, msg = add_book(title, author, isbn, copies, year, category)
                    if ok:
                        st.success(msg)
                    else:
                        st.error(msg)

        elif mode == "Edit / Delete Book":
            books = search_books()
            df = pd.DataFrame(books)
            if df.empty:
                st.write("No books available.")
            else:
                selected = st.selectbox("Pick book", df["title"] + " — " + df["author"])
                idx = df.index[df["title"] + " — " + df["author"] == selected][0]
                b = df.iloc[idx].to_dict()
                with st.form("edit_form"):
                    t = st.text_input("Title", value=b["title"])
                    a = st.text_input("Author", value=b["author"])
                    i = st.text_input("ISBN", value=b["isbn"])
                    tot = st.number_input("Total copies", value=int(b["copies_total"]), min_value=1)
                    y = st.number_input("Year", value=int(b.get("year") or datetime.utcnow().year))
                    cat = st.text_input("Category", value=b.get("category") or "")
                    submit_edit = st.form_submit_button("Save changes")
                    if submit_edit:
                        ok, msg = update_book(b["id"], t, a, i, tot, y, cat)
                        if ok:
                            st.success(msg)
                        else:
                            st.error(msg)
                if st.button("Delete book"):
                    delete_book(b["id"])
                    st.success("Deleted.")
                    st.experimental_rerun()

        else:
            st.info("Bulk upload via CSV: file should have columns: title,author,isbn,copies_total,year,category")
            uploaded = st.file_uploader("Upload CSV", type=["csv"])
            if uploaded:
                df = pd.read_csv(uploaded)
                count = 0
                for _, r in df.iterrows():
                    ok, _ = add_book(r.get("title",""), r.get("author",""), str(r.get("isbn","")), int(r.get("copies_total",1)), int(r.get("year", datetime.utcnow().year)), r.get("category",""))
                    if ok:
                        count += 1
                st.success(f"Imported {count} books.")

# Footer help
st.markdown("---")
st.markdown("**Note:** This is a small demo app using a local SQLite DB. For cloud deployment you would replace the DB with RDS / Cloud DB, add proper authentication (Cognito/Auth0), and secure password hashing.")
