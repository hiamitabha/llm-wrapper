import argparse
import sqlite3
import json
from datetime import datetime
from typing import Optional, List, Dict

DB_PATH = "monitor_events.db"


def init_db(db_path: str = DB_PATH):
    """Initialize the SQLite database for storing Parallel Monitor event groups."""
    conn = sqlite3.connect(db_path)
    c = conn.cursor()
    c.execute(
        """
        CREATE TABLE IF NOT EXISTS monitor_event_groups (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            monitor_id TEXT NOT NULL,
            event_group_id TEXT NOT NULL UNIQUE,
            metadata TEXT,
            received_at TEXT NOT NULL,
            processed INTEGER NOT NULL DEFAULT 0
        )
        """
    )
    conn.commit()
    conn.close()


def save_event_group(monitor_id: str, event_group_id: str, metadata: Optional[dict], db_path: str = DB_PATH):
    """Persist a new event group id if we haven't seen it before."""
    conn = sqlite3.connect(db_path)
    c = conn.cursor()
    c.execute(
        """
        INSERT OR IGNORE INTO monitor_event_groups (monitor_id, event_group_id, metadata, received_at, processed)
        VALUES (?, ?, ?, ?, 0)
        """,
        (monitor_id, event_group_id, json.dumps(metadata) if metadata else None, datetime.utcnow().isoformat()),
    )
    conn.commit()
    conn.close()


def fetch_unprocessed_event_groups(db_path: str = DB_PATH) -> List[Dict]:
    """Return all stored event group ids that have not been processed yet."""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    c.execute(
        "SELECT monitor_id, event_group_id, metadata, received_at "
        "FROM monitor_event_groups WHERE processed = 0 ORDER BY received_at ASC"
    )
    rows = c.fetchall()
    conn.close()
    return [dict(row) for row in rows]


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
        "SELECT id, monitor_id, event_group_id, metadata, received_at, processed "
        "FROM monitor_event_groups ORDER BY received_at DESC"
    )
    rows = c.fetchall()
    conn.close()
    
    if not rows:
        print("No event groups found in database.")
        return
    
    # Print header
    print(f"{'ID':<6} {'Monitor ID':<40} {'Event Group ID':<50} {'Processed':<10} {'Received At':<25} {'Metadata'}")
    print("-" * 180)
    
    # Print rows
    for row in rows:
        id_val, monitor_id, event_group_id, metadata, received_at, processed = row
        processed_str = "Yes" if processed else "No"
        metadata_str = metadata[:50] + "..." if metadata and len(metadata) > 50 else (metadata or "")
        print(f"{id_val:<6} {monitor_id:<40} {event_group_id:<50} {processed_str:<10} {received_at:<25} {metadata_str}")


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

    args = parser.parse_args()

    if args.command == "init":
        init_db(args.db_path)
        print(f"Initialized monitor DB schema at {args.db_path}")
    elif args.command == "list":
        list_all_events(args.db_path)


if __name__ == "__main__":
    main()

