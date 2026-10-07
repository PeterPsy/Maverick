"""Freshness and evidence-backed retirement of proposals as work evolves."""

import json

from learning_review_schema import POLICY_VERSION
from learning_store import audit, now


def invalidate_source(db, session):
    changed = False
    for row in db.execute("""SELECT DISTINCT i.id,i.details FROM learning_items i JOIN learning_item_sources s ON s.item_id=i.id
        WHERE s.session_id=? AND i.status IN ('pending','accepted','checking')""", (session,)).fetchall():
        details = json.loads(row["details"])
        if not details.get("review_stale"):
            details["review_stale"] = True
            db.execute("UPDATE learning_items SET details=?,updated_at=? WHERE id=?", (json.dumps(details), now(), row["id"]))
            changed = True
    return changed


def current_review(db, item, busy_sessions=()):
    details = json.loads(item["details"])
    if details.get("policy_version") != POLICY_VERSION or details.get("review_stale"):
        return False
    reviewed = details.get("reviewed_sources", {})
    sources = {x["session_id"] for x in json.loads(item["evidence"])}
    sources.update(x[0] for x in db.execute("SELECT session_id FROM learning_item_sources WHERE item_id=?", (item["id"],)))
    if not reviewed or sources - reviewed.keys():
        return False
    for session, revision in reviewed.items():
        if session in busy_sessions:
            return False
        state = db.execute("""SELECT c.busy,x.latest_turn_id FROM learning_conversations c
            LEFT JOIN learning_context x ON x.session_id=c.session_id WHERE c.session_id=?""", (session,)).fetchone()
        if not state or state["busy"] or state["latest_turn_id"] != revision:
            return False
    return True


def apply_review(db, job, review, input_data):
    db.execute("""INSERT INTO learning_context(session_id,episode_json) VALUES(?,?)
        ON CONFLICT(session_id) DO UPDATE SET episode_json=excluded.episode_json""",
        (job["session_id"], json.dumps(review["episode"])))
    for decision in review["reconciliations"]:
        item = db.execute("SELECT * FROM learning_items WHERE id=?", (decision["item_id"],)).fetchone()
        if not item or item["status"] not in {"pending", "accepted", "checking"}:
            continue
        ticket = db.execute("SELECT status FROM learning_implementations WHERE item_id=?", (item["id"],)).fetchone()
        details = json.loads(item["details"])
        details.update(review_reason=decision["reason"], review_disposition=decision["disposition"], review_evidence=decision["evidence"])
        if decision["disposition"] == "keep" and review["episode"]["status"] == "completed" and details.get("policy_version") == POLICY_VERSION:
            details["reviewed_sources"] = {**details.get("reviewed_sources", {}), **input_data.get("source_revisions", {})}
            details["review_stale"] = False
        elif decision["disposition"] != "keep" and (not ticket or ticket["status"] not in {"launching", "running", "stopping"}):
            db.execute("UPDATE learning_items SET status='rejected' WHERE id=?", (item["id"],))
            db.execute("UPDATE learning_implementations SET status='cancelled',updated_at=? WHERE item_id=?", (now(), item["id"]))
        else:
            details["review_stale"] = True
        db.execute("UPDATE learning_items SET details=?,updated_at=? WHERE id=?", (json.dumps(details), now(), item["id"]))
        audit(db, "review.reconciled." + decision["disposition"], item["id"])
