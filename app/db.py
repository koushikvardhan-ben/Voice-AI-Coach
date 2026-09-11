"""Small local SQLite store for the single-user coaching workspace."""
import json
import os
import sqlite3
import time
from contextlib import closing, contextmanager
from pathlib import Path

DB_PATH = Path(os.environ.get("WORKSPACE_DB_PATH", "data/workspace.sqlite3"))


@contextmanager
def connection():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(DB_PATH)) as db, db:
        db.row_factory = sqlite3.Row
        db.execute("CREATE TABLE IF NOT EXISTS records (kind TEXT, id TEXT, payload TEXT NOT NULL, PRIMARY KEY(kind, id))")
        yield db


def list_records(kind):
    with connection() as db:
        return [json.loads(r[0]) for r in db.execute("SELECT payload FROM records WHERE kind=? ORDER BY rowid DESC", (kind,))]


def get_record(kind, record_id):
    with connection() as db:
        row = db.execute("SELECT payload FROM records WHERE kind=? AND id=?", (kind, record_id)).fetchone()
        return json.loads(row[0]) if row else None


def save_record(kind, record):
    with connection() as db:
        db.execute("INSERT INTO records VALUES (?, ?, ?) ON CONFLICT(kind, id) DO UPDATE SET payload=excluded.payload", (kind, record["id"], json.dumps(record)))
    return record


def delete_record(kind, record_id):
    with connection() as db:
        return db.execute("DELETE FROM records WHERE kind=? AND id=?", (kind, record_id)).rowcount > 0


def initialize():
    if not get_record("meta", "initialized"):
        if list_records("agents"):
            save_record("meta", {"id": "initialized"})
            return
        for record_id, name, role, description, instructions in [
            ("buyer-coach", "Buyer discovery", "buyer", "Turn property enquiries into qualified viewings.", "Qualify location, budget, funding, decision makers and timeline. Address the latest concern before proposing a specific viewing. Never invent availability, prices or financing assurances."),
            ("vendor-coach", "Vendor advisory", "seller", "Build seller confidence and win valuation appointments.", "Explore the reason for selling, time on market, target price and previous agent experience. Acknowledge concerns about fees and pricing. Propose an evidence-led valuation; never guarantee a sale price or timeline."),
        ]:
            save_record("agents", {"id": record_id, "name": name, "role": role, "description": description, "instructions": instructions, "language": "en-IN", "knowledge_ids": [], "created_at": time.time()})
        save_record("meta", {"id": "initialized"})
