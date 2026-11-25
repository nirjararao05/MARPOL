"""Import the legacy MARPOL-SAFE SQLite database into MongoDB.

The Streamlit application itself uses MongoDB only. This one-time utility reads
marpol_safe.db and writes its six application tables to MongoDB collections.
"""

from __future__ import annotations

import argparse
import os
import sqlite3
import sys
from pathlib import Path

from pymongo import MongoClient


COLLECTIONS = (
    "records",
    "alerts",
    "audit",
    "attachments",
    "vessel_profile",
    "library_items",
)


def read_table(connection: sqlite3.Connection, table_name: str) -> list[dict]:
    rows = connection.execute(f'SELECT * FROM "{table_name}"').fetchall()
    columns = [item[1] for item in connection.execute(f'PRAGMA table_info("{table_name}")')]
    return [dict(zip(columns, row)) for row in rows]


def main() -> int:
    parser = argparse.ArgumentParser(description="Migrate MARPOL-SAFE SQLite data to MongoDB")
    parser.add_argument(
        "--source",
        default=str(Path(__file__).resolve().parent / "marpol_safe.db"),
        help="Path to the legacy SQLite database (default: ./marpol_safe.db)",
    )
    parser.add_argument(
        "--uri",
        default=os.getenv("MONGODB_URI", "mongodb://localhost:27017"),
        help="MongoDB connection string (default: MONGODB_URI or localhost)",
    )
    parser.add_argument(
        "--database",
        default=os.getenv("MONGODB_DATABASE", "marpol_safe"),
        help="MongoDB database name (default: MONGODB_DATABASE or marpol_safe)",
    )
    parser.add_argument(
        "--replace",
        action="store_true",
        help="Drop the target collections before importing; this deletes their current contents.",
    )
    args = parser.parse_args()

    source_path = Path(args.source).expanduser().resolve()
    if not source_path.is_file():
        print(f"SQLite source database not found: {source_path}", file=sys.stderr)
        return 1

    try:
        with sqlite3.connect(source_path) as sqlite_connection:
            imported = {name: read_table(sqlite_connection, name) for name in COLLECTIONS}

        client = MongoClient(args.uri, serverSelectionTimeoutMS=5000)
        client.admin.command("ping")
        database = client[args.database]

        non_empty = [name for name in COLLECTIONS if database[name].count_documents({}) > 0]
        if non_empty and not args.replace:
            print(
                "Import stopped because these MongoDB collections already contain data: "
                + ", ".join(non_empty)
                + ". Use --replace only when you intend to delete and replace their contents.",
                file=sys.stderr,
            )
            return 2

        for name in COLLECTIONS:
            if args.replace:
                database[name].drop()
            documents = imported[name]
            if documents:
                database[name].insert_many(documents)
            print(f"{name}: imported {len(documents)} document(s)")

        # Continue ID allocation after the highest imported integer ID.
        for name in COLLECTIONS:
            highest = max((doc.get("id", 0) or 0 for doc in imported[name]), default=0)
            database.counters.update_one(
                {"_id": name}, {"$max": {"seq": highest}}, upsert=True
            )

        database.records.create_index("record_id", unique=True)
        database.alerts.create_index("alert_id", unique=True)
        database.attachments.create_index("stored_name", unique=True)
        database.library_items.create_index("slug", unique=True)
        database.library_items.create_index([("annex", 1), ("content_type", 1)])

        print(f"\nMigration completed: {source_path} -> MongoDB database '{args.database}'.")
        print("The original SQLite file has not been modified or deleted.")
        return 0
    except Exception as error:
        print(f"Migration failed: {error}", file=sys.stderr)
        return 1
    finally:
        try:
            client.close()
        except (NameError, UnboundLocalError):
            pass


if __name__ == "__main__":
    raise SystemExit(main())
