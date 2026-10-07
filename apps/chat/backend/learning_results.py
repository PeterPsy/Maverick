"""Attempt-fenced result materialization and proposal aggregation."""

import json

from learning_queue import enqueue
from learning_store import audit, connection, new_id, now, settings
from learning_validation import normalize, review_output
from learning_reconciliation import apply_review


def complete_analysis(data_root, body):
    with connection(data_root, write=True) as db:
        state = body.get("status")
        usage = body.get("usage") if isinstance(body.get("usage"), dict) else {}
        tokens = usage.get("total_tokens", 0)
        tokens = tokens if isinstance(tokens, int) and not isinstance(tokens, bool) and tokens >= 0 else 0
        # Account for inference even when its result has been fenced by cancellation.
        db.execute("UPDATE learning_attempts SET usage=MAX(usage,?),status=CASE WHEN status='running' THEN ? ELSE status END WHERE request_id=? AND job_id=?",
                   (tokens, state or "failed", body.get("request_id", ""), body.get("job_id", "")))
        job = db.execute("SELECT * FROM learning_jobs WHERE id=? AND status='running' AND request_id=?",
                         (body.get("job_id", ""), body.get("request_id", ""))).fetchone()
        if not job:
            return {"ignored": True}
        if state == "busy":
            db.execute("UPDATE learning_attempts SET status='busy' WHERE request_id=?", (job["request_id"],))
            db.execute("UPDATE learning_jobs SET status='queued',attempts=MAX(0,attempts-1),reserved=0,reservation_day='',request_id='',due=? WHERE id=?",
                       (now() + 15, job["id"]))
            return {}
        error = str(body.get("error") or "Analysis failed")[:160]
        items = []
        if state == "completed":
            try:
                input_data = json.loads(job["input_json"])
                config = settings(db)
                for channel in ("memory_enabled", "improvements_enabled"):
                    input_data[channel] = input_data.get(channel, True) and config[channel]
                review = review_output(body.get("output_text", ""), input_data)
                items = review["items"]
                current = db.execute("SELECT latest_turn_id FROM learning_context WHERE session_id=?", (job["session_id"],)).fetchone()
                stale = current and current[0] != input_data.get("source_revisions", {}).get(job["session_id"])
                latest = db.execute("SELECT MAX(seq) FROM learning_exchanges WHERE session_id=?", (job["session_id"],)).fetchone()[0]
                stale = stale or (latest and latest > job["upto"])
                if stale:
                    items = []
                    review["episode"]["status"] = "ongoing"
                    review["reconciliations"] = []
                    apply_review(db, job, review, input_data)
                    audit(db, "analysis.superseded", job["id"])
                else:
                    apply_review(db, job, review, input_data)
            except (ValueError, KeyError, TypeError) as failure:
                state, error = "failed", str(failure)
        if state != "completed":
            status = "cancelled" if state == "cancelled" else ("queued" if job["attempts"] < 3 else "failed")
            db.execute("UPDATE learning_jobs SET status=?,error=?,usage=usage+?,due=?,updated_at=? WHERE id=?",
                       (status, error, tokens, now() + min(300, 15 * 2 ** job["attempts"]), now(), job["id"]))
            audit(db, "analysis." + status, job["id"])
            return {}
        requests = []
        provider = json.loads(job["input_json"]).get("memory_provider_app_id", "")
        for item in items:
            existing = db.execute("SELECT * FROM learning_items WHERE fingerprint=?", (item["fingerprint"],)).fetchone()
            if not existing:
                # A changed model-generated key must not recreate the same discarded content.
                existing = next((row for row in db.execute("SELECT * FROM learning_items WHERE kind=?", (item["kind"],))
                                 if normalize(row["body"]) == normalize(item["body"])), None)
            if existing:
                if existing["status"] in {"rejected", "implemented", "saved", "undone"}:
                    continue
                previous = json.loads(existing["evidence"])
                merged = {json.dumps(x, sort_keys=True): x for x in previous + item["evidence"]}
                db.execute("UPDATE learning_items SET evidence=?,occurrences=occurrences+1,updated_at=? WHERE id=?",
                           (json.dumps(list(merged.values())[-25:]), now(), existing["id"]))
                db.execute("INSERT OR IGNORE INTO learning_item_sources VALUES(?,?,?)", (existing["id"], job["id"], job["session_id"]))
                details = json.loads(existing["details"])
                details.update(policy_version=item["policy_version"], reviewed_sources={**details.get("reviewed_sources", {}), **item["reviewed_sources"]}, review_stale=False)
                db.execute("UPDATE learning_items SET details=? WHERE id=?", (json.dumps(details), existing["id"]))
                continue
            identifier = new_id("candidate" if item["kind"] == "memory" else "proposal")
            details = {key: value for key, value in item.items() if key not in {"title", "body", "evidence", "fingerprint", "kind"}}
            status = "checking" if item["kind"] == "memory" else "pending"
            operation = new_id("memory_check") if item["kind"] == "memory" else ""
            db.execute("INSERT INTO learning_items(id,fingerprint,kind,title,body,status,evidence,details,updated_at,operation_id,provider_id) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                       (identifier, item["fingerprint"], item["kind"], item["title"], item["body"], status,
                        json.dumps(item["evidence"]), json.dumps(details), now(), operation, provider))
            db.execute("INSERT OR IGNORE INTO learning_item_sources VALUES(?,?,?)", (identifier, job["id"], job["session_id"]))
            if item["kind"] == "memory":
                from learning_memory import dependency_request
                requests.append(dependency_request(identifier, "learning.memory_checked", {
                    "action": "search", "query": item["title"], "limit": 5}, operation_id=operation, provider_id=provider))
        db.execute("UPDATE learning_jobs SET status='completed',usage=usage+?,output_text=?,model=?,updated_at=? WHERE id=?",
                   (tokens, body["output_text"], str(body.get("provider_id", "")) + "/" + str(body.get("model_id", "")), now(), job["id"]))
        db.execute("UPDATE learning_conversations SET cursor=MAX(cursor,?) WHERE session_id=?", (job["upto"], job["session_id"]))
        pending = db.execute("SELECT MAX(seq) FROM learning_exchanges WHERE session_id=?", (job["session_id"],)).fetchone()[0]
        if pending and pending > job["upto"]:
            enqueue(db, job["session_id"], now())
        audit(db, "analysis.completed", job["id"])
        return {"dependency_backend_requests": requests, "_changed": True}
