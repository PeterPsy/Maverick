"""Attempt-fenced result materialization and proposal aggregation."""

import json

from learning_queue import enqueue
from learning_store import audit, connection, new_id, now
from learning_validation import validated_items


def complete_analysis(data_root, body):
    with connection(data_root, write=True) as db:
        job = db.execute("SELECT * FROM learning_jobs WHERE id=? AND status='running' AND request_id=?",
                         (body.get("job_id", ""), body.get("request_id", ""))).fetchone()
        if not job:
            return {"ignored": True}
        state = body.get("status")
        if state == "busy":
            db.execute("UPDATE learning_attempts SET status='busy' WHERE request_id=?", (job["request_id"],))
            db.execute("UPDATE learning_jobs SET status='queued',attempts=MAX(0,attempts-1),reserved=0,reservation_day='',request_id='',due=? WHERE id=?",
                       (now() + 15, job["id"]))
            return {}
        usage = body.get("usage") if isinstance(body.get("usage"), dict) else {}
        tokens = usage.get("total_tokens", 0)
        tokens = tokens if isinstance(tokens, int) and not isinstance(tokens, bool) and tokens >= 0 else 0
        db.execute("UPDATE learning_attempts SET usage=?,status=? WHERE request_id=?", (tokens, state, job["request_id"]))
        error = str(body.get("error") or "Analysis failed")[:160]
        items = []
        if state == "completed":
            try:
                items = validated_items(body.get("output_text", ""), json.loads(job["input_json"]))
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
            if existing:
                previous = json.loads(existing["evidence"])
                merged = {json.dumps(x, sort_keys=True): x for x in previous + item["evidence"]}
                db.execute("UPDATE learning_items SET evidence=?,occurrences=occurrences+1,updated_at=? WHERE id=?",
                           (json.dumps(list(merged.values())[-25:]), now(), existing["id"]))
                continue
            identifier = new_id("candidate" if item["kind"] == "memory" else "proposal")
            details = {key: value for key, value in item.items() if key not in {"title", "body", "evidence", "fingerprint", "kind"}}
            status = "checking" if item["kind"] == "memory" else "pending"
            operation = new_id("memory_check") if item["kind"] == "memory" else ""
            db.execute("INSERT INTO learning_items(id,fingerprint,kind,title,body,status,evidence,details,updated_at,operation_id,provider_id) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                       (identifier, item["fingerprint"], item["kind"], item["title"], item["body"], status,
                        json.dumps(item["evidence"]), json.dumps(details), now(), operation, provider))
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
