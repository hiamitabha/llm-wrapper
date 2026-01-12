import argparse
import sqlite3
import secrets
import string
from datetime import datetime, date

DB_PATH = "tokens/auth_tokens.db"

def generate_token(length=32):
    """Generate a random alphanumeric token of specified length."""
    alphabet = string.ascii_letters + string.digits
    return ''.join(secrets.choice(alphabet) for _ in range(length))

def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS tokens (
        token TEXT PRIMARY KEY,
        username TEXT NOT NULL,
        expiry DATETIME NOT NULL,
        request_count INTEGER NOT NULL DEFAULT 0,
        rate_limit INTEGER NOT NULL DEFAULT 15,
        last_request_date TEXT,
        lifetime_requests INTEGER NOT NULL DEFAULT 0
    )''')
    conn.commit()
    conn.close()

def modify_db():
    """Add new columns to existing database schema."""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    # Check if lifetime_requests column exists
    c.execute("PRAGMA table_info(tokens)")
    columns = [row[1] for row in c.fetchall()]

    if 'lifetime_requests' not in columns:
        c.execute('ALTER TABLE tokens ADD COLUMN lifetime_requests INTEGER NOT NULL DEFAULT 0')
        print("Added lifetime_requests column to tokens table.")
    else:
        print("lifetime_requests column already exists.")

    conn.commit()
    conn.close()

def add_token(username, expiry, rate_limit=15):
    try:
        # Validate expiry format
        datetime.strptime(expiry, "%Y-%m-%d %H:%M:%S")
    except ValueError:
        print("Expiry must be in 'YYYY-MM-DD HH:MM:SS' format.")
        return None
    token = generate_token()
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    today = date.today().isoformat()
    c.execute('''INSERT OR REPLACE INTO tokens 
        (token, username, expiry, request_count, rate_limit, last_request_date, lifetime_requests) 
        VALUES (?, ?, ?, 0, ?, ?, 0)''', (token, username, expiry, rate_limit, today))
    conn.commit()
    conn.close()
    print(f"Token generated for user '{username}' with expiry {expiry} and rate limit {rate_limit}.")
    print(f"Generated token: {token}")
    return token

def delete_token(token):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('DELETE FROM tokens WHERE token=?', (token,))
    conn.commit()
    conn.close()
    print(f"Token '{token}' deleted (if it existed).")

def list_tokens():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('SELECT token, username, expiry, request_count, rate_limit, last_request_date, lifetime_requests FROM tokens')
    rows = c.fetchall()
    conn.close()
    if not rows:
        print("No tokens found.")
        return
    print(f"{'Token':<30} {'Username':<20} {'Expiry':<20} {'ReqCount':<10} {'RateLimit':<10} {'LastReqDate':<12} {'Lifetime'}")
    print("-"*120)
    for token, username, expiry, request_count, rate_limit, last_request_date, lifetime_requests in rows:
        print(f"{token:<30} {username:<20} {expiry:<20} {request_count:<10} {rate_limit:<10} {last_request_date:<12} {lifetime_requests}")

def main():
    parser = argparse.ArgumentParser(description="Manage authorization tokens in SQLite DB.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    # Add
    add_parser = subparsers.add_parser('add', help='Add a new token')
    add_parser.add_argument('--username', required=True, help='Username')
    add_parser.add_argument('--expiry', required=True, help="Expiry in 'YYYY-MM-DD HH:MM:SS' format")
    add_parser.add_argument('--rate_limit', type=int, default=15, help='Requests per day limit (default 15)')

    # Delete
    del_parser = subparsers.add_parser('delete', help='Delete a token')
    del_parser.add_argument('--token', required=True, help='Token string to delete')

    # List
    list_parser = subparsers.add_parser('list', help='List all tokens')

    # Modify
    modify_parser = subparsers.add_parser('modify', help='Modify database schema')

    args = parser.parse_args()
    init_db()
    if args.command == 'add':
        add_token(args.username, args.expiry, args.rate_limit)
    elif args.command == 'delete':
        delete_token(args.token)
    elif args.command == 'list':
        list_tokens()
    elif args.command == 'modify':
        modify_db()

if __name__ == "__main__":
    main() 

