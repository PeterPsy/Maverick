"""Remove deleted source evidence and fence unsaved learning work."""

import json

from learning_store import audit, connection, now, settings


def cleanup(root, session_ids):
    cancellations = []
    remaining_sources = set()
    with connection(root, write=True) as db:
        for session in session_ids:
            db.execute("""UPDATE learning_implementations SET status='cancelled',session_id='',turn_id='',
                request_id='',request_json='{}',error='Work chat was deleted',updated_at=? WHERE session_id=?""", (now(), session))
            cancellations.extend(x[0] for x in db.execute("SELECT request_id FROM learning_jobs WHERE session_id=? AND status='running'", (session,)))
            db.execute("UPDATE learning_jobs SET status='cancelled',request_id='' WHERE session_id=? AND status IN ('queued','running')", (session,))
            db.execute("DELETE FROM learning_exchanges WHERE session_id=?", (session,))
            db.execute("DELETE FROM learning_conversations WHERE session_id=?", (session,))
            db.execute("DELETE FROM learning_context WHERE session_id=?", (session,))
            db.execute("UPDATE learning_jobs SET input_json='{}',output_text='' WHERE session_id=?", (session,))
            for item in db.execute("SELECT * FROM learning_items WHERE status IN ('checking','pending','accepted','rejected')").fetchall():
                evidence = json.loads(item["evidence"])
                details = json.loads(item["details"])
                linked = db.execute("SELECT 1 FROM learning_item_sources WHERE item_id=? AND session_id=?", (item["id"], session)).fetchone()
                remaining = [x for x in evidence if x["session_id"] != session]
                if len(remaining) == len(evidence) and not linked and session not in details.get("reviewed_sources", {}):
                    continue
                details.get("reviewed_sources", {}).pop(session, None)
                details.update(review_stale=True, review_reason="A source chat was deleted; reassess the remaining evidence")
                db.execute("DELETE FROM learning_item_sources WHERE item_id=? AND session_id=?", (item["id"], session))
                ticket = db.execute("SELECT status FROM learning_implementations WHERE item_id=?", (item["id"],)).fetchone()
                active = ticket and ticket["status"] in {"launching", "running", "stopping"}
                status = item["status"] if remaining or active else "rejected"
                db.execute("UPDATE learning_items SET evidence=?,details=?,status=?,updated_at=? WHERE id=?",
                    (json.dumps(remaining), json.dumps(details), status, now(), item["id"]))
                if not remaining:
                    db.execute("""UPDATE learning_implementations SET status='cancelled',error='Source chat was deleted',
                        updated_at=? WHERE item_id=? AND status='queued'""", (now(), item["id"]))
                elif status != "rejected":
                    remaining_sources.update(x["session_id"] for x in remaining)
                audit(db, "review.source_deleted", item["id"])
        for session in remaining_sources:
            running = db.execute("SELECT request_id FROM learning_jobs WHERE session_id=? AND status='running'", (session,)).fetchall()
            if not running:
                continue
            cancellations.extend(row[0] for row in running)
            queued = db.execute("SELECT 1 FROM learning_jobs WHERE session_id=? AND status='queued'", (session,)).fetchone()
            # Fence the old source snapshot and keep at most one claim for the remaining evidence.
            db.execute("""UPDATE learning_jobs SET status=?,request_id='',attempts=0,due=?,updated_at=?
                WHERE session_id=? AND status='running'""",
                ("cancelled" if queued else "queued", now() + settings(db)["idle_seconds"], now(), session))
    return {"background_generation_cancel_requests": cancellations}
