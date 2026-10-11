"""Current observation identity, independent of immutable version deduplication."""

import sqlite3


def observe_version(db: sqlite3.Connection, source_id: str, version_id: str) -> bool:
    row = db.execute("SELECT current_version_id FROM sources WHERE id = ?", (source_id,)).fetchone()
    changed = row is None or row["current_version_id"] != version_id
    db.execute("UPDATE sources SET current_version_id = ? WHERE id = ?", (version_id, source_id))
    return changed


def current_version_id(db: sqlite3.Connection, source_id: str) -> str:
    row = db.execute("SELECT current_version_id FROM sources WHERE id = ?", (source_id,)).fetchone()
    return str(row["current_version_id"] or "") if row is not None else ""
