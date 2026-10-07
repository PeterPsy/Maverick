"""Administrator-requested dismissal of the learning backlog, retaining its audit."""

import json

from learning_store import audit, now


def discard_all(db, actor):
    if db.execute("SELECT 1 FROM learning_items WHERE status IN ('saving','undoing')").fetchone():
        raise ValueError("Wait for the Memory provider operation to finish before discarding the backlog")
    counts = {"memory": 0, "improvement": 0}
    for item in db.execute("SELECT * FROM learning_items WHERE status NOT IN ('rejected','saved','undone')").fetchall():
        details = json.loads(item["details"])
        details.update(discarded_by_user=True, review_reason="Discarded by the administrator; superseded review criteria")
        db.execute("UPDATE learning_items SET status='rejected',details=?,updated_at=? WHERE id=?",
                   (json.dumps(details), now(), item["id"]))
        counts[item["kind"]] += 1
        audit(db, "review.discard_all", item["id"], actor)
    interrupts = [{"turn_id": x["turn_id"], "reason": "Learning backlog discarded by administrator"}
                  for x in db.execute("SELECT turn_id FROM learning_implementations WHERE status IN ('launching','running','stopping') AND turn_id!=''")]
    db.execute("""UPDATE learning_implementations SET status=CASE WHEN status IN ('launching','running','stopping')
        THEN 'stopping' ELSE 'cancelled' END,updated_at=? WHERE status!='saved'""", (now(),))
    cancellations = [x[0] for x in db.execute("SELECT request_id FROM learning_jobs WHERE status='running' AND request_id!=''")]
    db.execute("UPDATE learning_jobs SET status='cancelled',request_id='',updated_at=? WHERE status IN ('queued','running')", (now(),))
    db.execute("""UPDATE learning_conversations SET cursor=COALESCE(
        (SELECT MAX(seq) FROM learning_exchanges e WHERE e.session_id=learning_conversations.session_id),cursor)""")
    db.execute("UPDATE learning_context SET episode_json='{}'")
    audit(db, "backlog.discarded", actor=actor)
    return {"discarded": counts, "runtime_turn_interrupt_requests": interrupts,
            "background_generation_cancel_requests": cancellations, "_changed": True}
