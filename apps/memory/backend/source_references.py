"""Shared source-status boundary for external references in ordinary retrieval."""

import sqlite3

# An attached reference without a materialized source remains usable. Once its
# source is removed, every ordinary reference projection must respect removal.
ACTIVE_REFERENCE_SQL = "NOT EXISTS(SELECT 1 FROM sources s WHERE s.external_ref_id = r.id AND s.status != 'active')"


def external_refs_for_nodes(db: sqlite3.Connection, node_ids: list[str], *, include_removed: bool = False) -> list[sqlite3.Row]:
    if not node_ids:
        return []
    marks = ",".join("?" for _ in node_ids)
    active_clause = "" if include_removed else "AND " + ACTIVE_REFERENCE_SQL
    return list(db.execute(f"""SELECT r.* FROM external_refs r
        WHERE r.node_id IN ({marks}) {active_clause} ORDER BY r.created_at""", node_ids))


def external_ref_by_id(db: sqlite3.Connection, ref_id: str, *, include_removed: bool = False) -> sqlite3.Row | None:
    active_clause = "" if include_removed else "AND " + ACTIVE_REFERENCE_SQL
    return db.execute(f"SELECT r.* FROM external_refs r WHERE r.id = ? {active_clause}", (ref_id,)).fetchone()
