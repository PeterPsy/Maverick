"""Stable identities and inspectable snapshots for fact changes."""

import json
import sqlite3

from database import json_text, new_id, now_timestamp, row_payload


def save_revision(db: sqlite3.Connection, node_id: str, reason: str) -> None:
    node = row_payload(db.execute("SELECT * FROM nodes WHERE id = ?", (node_id,)).fetchone())
    if node:
        db.execute("""INSERT INTO node_revisions(id, node_id, revision, reason, snapshot_json, created_at)
            VALUES (?, ?, ?, ?, ?, ?)""", (new_id("rev"), node_id, node["updated_at"], reason, json_text(node), now_timestamp()))


def revisions_for_node(db: sqlite3.Connection, node_id: str) -> list[dict]:
    return [{"id": row["id"], "revision": row["revision"], "reason": row["reason"], "created_at": row["created_at"], "snapshot": json.loads(row["snapshot_json"])} for row in db.execute(
        "SELECT id, revision, reason, snapshot_json, created_at FROM node_revisions WHERE node_id = ? ORDER BY created_at DESC LIMIT 30",
        (node_id,))]
