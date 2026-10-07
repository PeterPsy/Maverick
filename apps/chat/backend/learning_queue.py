"""Evidence capture, debounce, durable claims and generation requests."""

from datetime import UTC, datetime
import json
import re

from learning_store import audit, connection, daily_consumption, new_id, now, settings
from learning_review_schema import OUTPUT_SCHEMA, SYSTEM_PROMPT
from learning_input import build_input

_SECRET = re.compile(r"(?i)(bearer\s+\S+|(?:api[_-]?key|password|secret|token)\s*[:=]\s*[^\s,;]+)")
_JSON_SECRET = re.compile(r'''(?i)(["'](?:api[_-]?key|password|secret|token)["']\s*:\s*)["'][^"']+["']''')
_PRIVATE_KEY = re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----", re.DOTALL)
BUDGET_WAIT_REASON = "Daily token allowance cannot cover the next analysis"


def clean(text, limit=16_000):
    value = _PRIVATE_KEY.sub("[redacted]", str(text or ""))
    value = _JSON_SECRET.sub(r'\1"[redacted]"', value)
    return _SECRET.sub("[redacted]", value)[:limit]


def capture(data_root, body):
    session = str(body.get("runtime_session_id") or "")
    if not session or body.get("session_kind") != "chat_root" or body.get("thread_visibility") != "user":
        return {}
    with connection(data_root, write=True) as db:
        config = settings(db)
        if db.execute("SELECT 1 FROM learning_implementations WHERE session_id=?", (session,)).fetchone():
            return {}
        if not config["enabled"] or excluded(config, session, body.get("project_id", "")):
            return {}
        action = body.get("action")
        if action not in {"runtime.turn.queued", "runtime.turn.completed", "runtime.turn.failed", "runtime.turn.cancelled"}:
            return {}
        if body.get("recovered"):
            completed = datetime.fromisoformat(body["completed_at"]).timestamp()
            if completed < config.get("capture_started_at", now()):
                return {}
        if db.execute("SELECT 1 FROM learning_exchanges WHERE turn_id=?", (body.get("turn_id", ""),)).fetchone():
            return {}
        timestamp = now()
        db.execute("""INSERT INTO learning_context(session_id,current_input,latest_turn_id) VALUES(?,?,?)
            ON CONFLICT(session_id) DO UPDATE SET current_input=excluded.current_input,latest_turn_id=excluded.latest_turn_id""",
            (session, clean(body.get("input_text"), 4000) if action == "runtime.turn.queued" else "", body.get("turn_id", "")))
        from learning_reconciliation import invalidate_source
        invalidated = invalidate_source(db, session)
        db.execute("""INSERT INTO learning_conversations(session_id,project_id,busy,last_activity)
                      VALUES(?,?,?,?) ON CONFLICT(session_id) DO UPDATE SET
                      busy=excluded.busy,last_activity=excluded.last_activity,project_id=excluded.project_id""",
                   (session, body.get("project_id", ""), int(action == "runtime.turn.queued"), timestamp))
        if action == "runtime.turn.queued":
            cancellations = [x[0] for x in db.execute("SELECT request_id FROM learning_jobs WHERE session_id=? AND status='running'", (session,))]
            db.execute("UPDATE learning_jobs SET status='queued',request_id='',attempts=0,due=?,updated_at=? WHERE session_id=? AND status='running'",
                       (timestamp + config["idle_seconds"], timestamp, session))
            return {"background_generation_cancel_requests": cancellations, "_changed": bool(cancellations) or invalidated}
        if action not in {"runtime.turn.completed", "runtime.turn.failed", "runtime.turn.cancelled"}:
            return {}
        inserted = db.execute("""INSERT OR IGNORE INTO learning_exchanges
                     (session_id,turn_id,status,input_text,output_text,metrics,created_at) VALUES(?,?,?,?,?,?,?)""",
            (session, body["turn_id"], body.get("turn_status", "failed"), clean(body.get("input_text")),
             clean(body.get("output_text")), json.dumps(body.get("metrics", {})), timestamp)).rowcount
        if inserted:
            enqueue(db, session, timestamp + config["idle_seconds"])
    return {"_changed": bool(inserted)}


def excluded(config, session, project):
    return session in config["excluded_thread_ids"] or (project and project in config["excluded_project_ids"])


def enqueue(db, session, due, *, reschedule=True, reassess_after=0):
    row = db.execute("SELECT MAX(seq) FROM learning_exchanges WHERE session_id=?", (session,)).fetchone()
    if not row or not row[0]:
        return
    # A source-set change requires another pass; existing claims and later terminal jobs cover it.
    if not reschedule and db.execute("""SELECT 1 FROM learning_jobs WHERE session_id=? AND upto>=?
        AND (status IN ('queued','running') OR updated_at>=?)""", (session, row[0], reassess_after)).fetchone():
        return
    pending = db.execute("SELECT id FROM learning_jobs WHERE session_id=? AND status='queued'", (session,)).fetchone()
    if pending:
        db.execute("UPDATE learning_jobs SET upto=?,due=?,updated_at=? WHERE id=?", (row[0], due, now(), pending[0]))
    else:
        db.execute("INSERT INTO learning_jobs(id,session_id,status,upto,due,created_at,updated_at) VALUES(?,?,'queued',?,?,?,?)",
                   (new_id("analysis"), session, row[0], due, now(), now()))


def tick(data_root, body):
    if body.get("action") == "backend.recovery":
        for evidence in body.get("recent_terminal_exchanges", []):
            capture(data_root, {**evidence, "recovered": True})
    with connection(data_root, write=True) as db:
        config = settings(db)
        if body.get("action") == "backend.recovery":
            db.execute("UPDATE learning_jobs SET status='queued',request_id='',due=?,updated_at=? WHERE status='running'", (now(), now()))
            audit(db, "recovery")
            return {"next_due_in_seconds": 5, "_changed": True}
        cutoff = now() - config["retention_days"] * 86400
        db.execute("DELETE FROM learning_exchanges WHERE created_at<?", (cutoff,))
        db.execute("DELETE FROM learning_audit WHERE created_at<?", (cutoff,))
        db.execute("DELETE FROM learning_attempts WHERE day<?", (datetime.fromtimestamp(cutoff, UTC).date().isoformat(),))
        db.execute("UPDATE learning_jobs SET input_json='{}',output_text='' WHERE updated_at<? AND status IN ('completed','failed','cancelled')", (cutoff,))
        # Reconcile app effects that may have committed before their callback was lost.
        stale = db.execute("SELECT * FROM learning_items WHERE status IN ('saving','checking','undoing') AND updated_at<? LIMIT 1", (now() - 90,)).fetchone()
        if stale:
            from learning_memory import dependency_request, save_request
            if stale["status"] == "saving":
                return {"dependency_backend_requests": [save_request(db, stale, target_node_id=json.loads(stale["details"]).get("target_node_id", ""))], "next_due_in_seconds": 15}
            if stale["status"] == "checking":
                token = new_id("memory_check")
                db.execute("UPDATE learning_items SET operation_id=?,updated_at=? WHERE id=?", (token, now(), stale["id"]))
                return {"dependency_backend_requests": [dependency_request(stale["id"], "learning.memory_checked", {"action": "search", "query": stale["title"], "limit": 5}, operation_id=token, provider_id=stale["provider_id"])], "next_due_in_seconds": 15}
            # A repeated guarded delete is idempotently reconciled by Memory.
            details = json.loads(stale["details"])
            db.execute("UPDATE learning_items SET updated_at=? WHERE id=?", (now(), stale["id"]))
            return {"dependency_backend_requests": [dependency_request(stale["id"], "learning.memory_undone", {
                "action": "delete_node", "node_id": stale["node_id"],
                "expected_updated_at": details.get("node_updated_at", ""), "reason": "conversation_learning_undo"},
                operation_id=stale["operation_id"], provider_id=stale["provider_id"])], "next_due_in_seconds": 15}
        if not config["enabled"] or config["paused"] or not (config["memory_enabled"] or config["improvements_enabled"]):
            return {"next_due_in_seconds": 60}
        active = db.execute("SELECT * FROM learning_jobs WHERE status='running' LIMIT 1").fetchone()
        if active:
            if now() - active["updated_at"] > config["timeout_seconds"] + 90:
                db.execute("UPDATE learning_jobs SET status='queued',request_id='',due=? WHERE id=?", (now(), active["id"]))
                return {"background_generation_cancel_requests": [active["request_id"]], "next_due_in_seconds": 15}
            return {"next_due_in_seconds": 15}
        busy = set(body.get("busy_runtime_session_ids", []))
        rows = db.execute("""SELECT j.*,c.project_id,c.last_activity,c.cursor,c.busy FROM learning_jobs j
                            JOIN learning_conversations c ON c.session_id=j.session_id
                            WHERE j.status='queued' AND j.due<=? ORDER BY j.created_at""", (now(),)).fetchall()
        changed = False
        row = None
        for candidate in rows:
            if candidate["attempts"] >= 3:
                db.execute("UPDATE learning_jobs SET status='failed',error='Analysis retry limit reached',updated_at=? WHERE id=?", (now(), candidate["id"]))
                changed = True
            elif excluded(config, candidate["session_id"], candidate["project_id"]):
                db.execute("UPDATE learning_jobs SET status='cancelled',updated_at=? WHERE id=?", (now(), candidate["id"]))
                changed = True
            elif candidate["session_id"] in busy or (candidate["busy"] and not body.get("runtime_status_complete")) or now() < candidate["last_activity"] + config["idle_seconds"]:
                db.execute("UPDATE learning_jobs SET due=? WHERE id=?", (now() + 15, candidate["id"]))
            else:
                row = candidate
                break
        if not row:
            return {"next_due_in_seconds": 15 if rows else 30, "_changed": changed}
        input_data = build_input(db, row, config, memory_provider_app_id=body.get("memory_provider_app_id", ""))
        exchanges = input_data["exchanges"]
        if not exchanges:
            db.execute("UPDATE learning_jobs SET status='completed' WHERE id=?", (row["id"],))
            return {"next_due_in_seconds": 1}
        prompt = json.dumps(input_data, ensure_ascii=False)
        system = SYSTEM_PROMPT + "\nOptional focus guidance (the review mandate remains authoritative):\n" + config["instructions"]
        # Native Codex also receives its fixed provider instructions.
        native_overhead = 8000 if config["model_source"] == "workspace" else 0
        reservation = native_overhead + (len(prompt) + len(system)) // 3 + config["max_output_tokens"]
        day = datetime.now(UTC).date().isoformat()
        used = daily_consumption(db, day)
        if used + reservation > config["daily_token_budget"]:
            updated = db.execute("UPDATE learning_jobs SET error=?,updated_at=? WHERE id=? AND error!=?",
                                 (BUDGET_WAIT_REASON, now(), row["id"], BUDGET_WAIT_REASON)).rowcount
            return {"next_due_in_seconds": 60, "budget_exhausted": True, "_changed": changed or bool(updated)}
        token = new_id("attempt")
        db.execute("INSERT INTO learning_attempts(request_id,job_id,day,reserved) VALUES(?,?,?,?)", (token, row["id"], day, reservation))
        db.execute("""UPDATE learning_jobs SET status='running',upto=?,request_id=?,attempts=attempts+1,
                      updated_at=?,reserved=?,reservation_day=?,input_json=?,error='' WHERE id=?""",
                   (exchanges[-1]["seq"], token, now(), reservation, day, prompt, row["id"]))
        audit(db, "analysis.started", row["id"])
        return {"next_due_in_seconds": 15, "_changed": True, "background_generation_requests": [{
            "request_id": token, "exclusive_key": "conversation-learning", "input_text": prompt,
            "system_prompt": system, "output_schema": OUTPUT_SCHEMA,
            "model_source": config["model_source"], "model_id": config["model_id"],
            "reasoning_effort": config["reasoning_effort"], "timeout_seconds": config["timeout_seconds"],
            "max_output_tokens": config["max_output_tokens"],
            "callback": {"action": "learning.analysis_completed", "payload": {"job_id": row["id"]}},
            "admission": {"action": "learning.analysis_admit", "payload": {"job_id": row["id"]}},
        }]}
