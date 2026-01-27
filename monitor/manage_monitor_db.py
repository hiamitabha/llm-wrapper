import argparse
import sqlite3
import json
from datetime import datetime
from typing import Optional, List, Dict, Any

# Use the same SQLite DB as token management so we have one DB with two tables.
DB_PATH = "tokens/auth_tokens.db"


def init_db(db_path: str = DB_PATH):
    """Initialize the SQLite database table for storing Parallel Monitor event groups."""
    conn = sqlite3.connect(db_path)
    c = conn.cursor()
    c.execute(
        """
        CREATE TABLE IF NOT EXISTS monitor_event_groups (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT NOT NULL,
            monitor_id TEXT NOT NULL,
            event_group_id TEXT NOT NULL UNIQUE,
            metadata TEXT,
            received_at TEXT NOT NULL,
            processed INTEGER NOT NULL DEFAULT 0
        )
        """
    )
    c.execute("CREATE INDEX IF NOT EXISTS idx_monitor_event_groups_username_processed_received ON monitor_event_groups (username, processed, received_at)")
    conn.commit()
    conn.close()


def username_exists(username: str, db_path: str = DB_PATH) -> bool:
    """Return True if the given username exists in the tokens table."""
    conn = sqlite3.connect(db_path)
    c = conn.cursor()
    try:
        c.execute("SELECT 1 FROM tokens WHERE username = ? LIMIT 1", (username,))
        row = c.fetchone()
        return row is not None
    except sqlite3.OperationalError:
        # tokens table may not exist yet
        return False
    finally:
        conn.close()


def register_monitor(username: str, monitor_id: str, db_path: str = DB_PATH) -> bool:
    """Register a monitor_id -> username mapping by creating a placeholder event group record.
    This allows the webhook to look up username by monitor_id even before the first event arrives.
    Creates a special "registration" event_group_id that can be used to establish the mapping.
    """
    if not username or not monitor_id:
        return False
    if not username_exists(username, db_path=db_path):
        return False

    # Use a special event_group_id to mark this as a registration record
    registration_event_group_id = f"__registration__{monitor_id}"
    conn = sqlite3.connect(db_path)
    c = conn.cursor()
    # Check if monitor is already registered
    c.execute("SELECT 1 FROM monitor_event_groups WHERE monitor_id = ? LIMIT 1", (monitor_id,))
    if c.fetchone():
        conn.close()
        return True  # Already registered
    # Insert registration record (marked as processed so it doesn't show up in event queries)
    c.execute(
        """
        INSERT OR IGNORE INTO monitor_event_groups (username, monitor_id, event_group_id, metadata, received_at, processed)
        VALUES (?, ?, ?, ?, ?, 1)
        """,
        (username, monitor_id, registration_event_group_id, json.dumps({"type": "registration"}), datetime.utcnow().isoformat()),
    )
    inserted = c.rowcount > 0
    conn.commit()
    conn.close()
    return inserted

def save_event_group(username: str, monitor_id: str, event_group_id: str, metadata: Optional[dict], db_path: str = DB_PATH) -> bool:
    """Persist a new event group id if we haven't seen it before."""
    if not username:
        return False
    if not username_exists(username, db_path=db_path):
        return False

    conn = sqlite3.connect(db_path)
    c = conn.cursor()
    c.execute(
        """
        INSERT OR IGNORE INTO monitor_event_groups (username, monitor_id, event_group_id, metadata, received_at, processed)
        VALUES (?, ?, ?, ?, ?, 0)
        """,
        (username, monitor_id, event_group_id, json.dumps(metadata) if metadata else None, datetime.utcnow().isoformat()),
    )
    inserted = c.rowcount > 0
    conn.commit()
    conn.close()
    return inserted


def fetch_unprocessed_event_groups(username: str, db_path: str = DB_PATH) -> List[Dict[str, Any]]:
    """Return all stored event group ids (and metadata) that have not been processed yet for a given user."""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    c.execute(
        "SELECT username, monitor_id, event_group_id, metadata, received_at "
        "FROM monitor_event_groups WHERE username = ? AND processed = 0 ORDER BY received_at ASC",
        (username,),
    )
    rows = c.fetchall()
    conn.close()
    return [dict(row) for row in rows]


def get_username_by_monitor_id(monitor_id: str, db_path: str = DB_PATH) -> Optional[str]:
    """Look up the username associated with a monitor_id from the monitor_event_groups table.
    Returns the username if found, None otherwise.
    This works by finding any existing event group record for the monitor_id.
    """
    conn = sqlite3.connect(db_path)
    c = conn.cursor()
    c.execute(
        "SELECT DISTINCT username FROM monitor_event_groups WHERE monitor_id = ? LIMIT 1",
        (monitor_id,)
    )
    row = c.fetchone()
    conn.close()
    return row[0] if row else None


def mark_event_group_processed(event_group_id: str, db_path: str = DB_PATH):
    """Mark an event group as processed so it is not resent."""
    conn = sqlite3.connect(db_path)
    c = conn.cursor()
    c.execute("UPDATE monitor_event_groups SET processed = 1 WHERE event_group_id = ?", (event_group_id,))
    conn.commit()
    conn.close()


def list_all_events(db_path: str = DB_PATH):
    """Print all event groups stored in the database."""
    conn = sqlite3.connect(db_path)
    c = conn.cursor()
    c.execute(
        "SELECT id, username, monitor_id, event_group_id, metadata, received_at, processed "
        "FROM monitor_event_groups ORDER BY received_at DESC"
    )
    rows = c.fetchall()
    conn.close()
    
    if not rows:
        print("No event groups found in database.")
        return
    
    # Print header
    print(f"{'ID':<6} {'Username':<20} {'Monitor ID':<40} {'Event Group ID':<50} {'Processed':<10} {'Received At':<25} {'Metadata'}")
    print("-" * 205)
    
    # Print rows
    for row in rows:
        id_val, username, monitor_id, event_group_id, metadata, received_at, processed = row
        processed_str = "Yes" if processed else "No"
        metadata_str = metadata[:50] + "..." if metadata and len(metadata) > 50 else (metadata or "")
        print(f"{id_val:<6} {username:<20} {monitor_id:<40} {event_group_id:<50} {processed_str:<10} {received_at:<25} {metadata_str}")


def main():
    parser = argparse.ArgumentParser(description="Manage Parallel Monitor event-group storage DB.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    init_parser = subparsers.add_parser("init", help="Initialize the monitor events database schema")
    init_parser.add_argument(
        "--db_path",
        default=DB_PATH,
        help=f"SQLite DB path (default: {DB_PATH})",
    )

    list_parser = subparsers.add_parser("list", help="List all event groups in the database")
    list_parser.add_argument(
        "--db_path",
        default=DB_PATH,
        help=f"SQLite DB path (default: {DB_PATH})",
    )

    list_user_parser = subparsers.add_parser("list-user", help="List all event groups for a specific username")
    list_user_parser.add_argument("--username", required=True, help="Username to filter by")
    list_user_parser.add_argument(
        "--db_path",
        default=DB_PATH,
        help=f"SQLite DB path (default: {DB_PATH})",
    )

    args = parser.parse_args()

    if args.command == "init":
        init_db(args.db_path)
        print(f"Initialized monitor DB schema at {args.db_path}")
    elif args.command == "list":
        list_all_events(args.db_path)
    elif args.command == "list-user":
        conn = sqlite3.connect(args.db_path)
        c = conn.cursor()
        c.execute(
            "SELECT id, username, monitor_id, event_group_id, metadata, received_at, processed "
            "FROM monitor_event_groups WHERE username = ? ORDER BY received_at DESC",
            (args.username,),
        )
        rows = c.fetchall()
        conn.close()
        if not rows:
            print(f"No event groups found for username={args.username}")
            return
        print(f"{'ID':<6} {'Username':<20} {'Monitor ID':<40} {'Event Group ID':<50} {'Processed':<10} {'Received At':<25} {'Metadata'}")
        print("-" * 205)
        for row in rows:
            id_val, username, monitor_id, event_group_id, metadata, received_at, processed = row
            processed_str = "Yes" if processed else "No"
            metadata_str = metadata[:50] + "..." if metadata and len(metadata) > 50 else (metadata or "")
            print(f"{id_val:<6} {username:<20} {monitor_id:<40} {event_group_id:<50} {processed_str:<10} {received_at:<25} {metadata_str}")


if __name__ == "__main__":
    main()

