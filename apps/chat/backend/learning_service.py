"""Administrative learning workflows and trusted lifecycle dispatch."""

import json

from learning_memory import dependency_request, memory_callback
from learning_queue import BUDGET_WAIT_REASON, capture, enqueue, excluded, tick
from learning_results import complete_analysis
from learning_store import audit, connection, daily_consumption, now, settings, validate_settings
import learning_implementations as implementations
from learning_projects import learning_projects


def handle_learning(payload):
    root, body = payload["data_root"], payload.get("body", {})
    action, surface = body.get("action", ""), payload.get("surface", "")
    if action == "learning.memory_agent":
        from learning_memory_agent import memory_agent_action
        return memory_agent_action(payload)
    if surface == "runtime_event":
        ticket_event = implementations.runtime_event(root, body)
        return ticket_event if ticket_event is not None else capture(root, body)
    if surface in {"background_tick", "backend_recovery"}:
        if surface == "backend_recovery":
            for event in body.get("recent_terminal_exchanges", []):
                implementations.runtime_event(root, event)
        tickets = implementations.tick(root, body)
        learning = tick(root, {**body, "memory_provider_app_id": selected_memory_provider(payload)})
        return {**learning, **tickets, "_changed": learning.get("_changed", False) or tickets.get("_changed", False),
                "next_due_in_seconds": min(learning.get("next_due_in_seconds", 30), tickets["next_due_in_seconds"])}
    if action == "learning.implementation_started":
        if surface != "runtime_request_callback":
            raise PermissionError("Trusted implementation callback required")
        return implementations.started(root, body)
    if action == "learning.analysis_admit":
        if surface != "background_generation_admission":
            raise PermissionError("Trusted analysis admission required")
        with connection(root) as db:
            config = settings(db)
            job = db.execute("SELECT 1 FROM learning_jobs WHERE id=? AND request_id=? AND status='running'", (body.get("job_id", ""), body.get("request_id", ""))).fetchone()
            return {"allowed": bool(job and config["enabled"] and not config["paused"])}
    if action == "learning.analysis_completed":
        if surface != "background_generation_callback":
            raise PermissionError("Trusted analysis callback required")
        return complete_analysis(root, body)
    if action in {"learning.memory_checked", "learning.memory_saved", "learning.memory_undone"}:
        if surface != "dependency_backend_request_callback":
            raise PermissionError("Trusted Memory callback required")
        return memory_callback(root, body)
    if action == "runtime.cleanup_sessions" and payload.get("effective_mode") == "full-access" and not payload.get("user_id"):
        return cleanup(root, body.get("runtime_session_ids", []))
    if payload.get("platform_role") != "admin" and payload.get("workspace_role") != "admin":
        raise PermissionError("Learning requires workspace administrator access")
    actor = payload.get("user_id") or "operator"
    with connection(root, write=True) as db:
        if action == "learning.read":
            return {**dashboard(db), "projects": learning_projects(root)[0]}
        if action == "learning.discard_all":
            from learning_reset import discard_all
            return discard_all(db, actor)
        if action == "learning.configure":
            previous = settings(db)
            config = validate_settings(body.get("settings", {}), previous)
            if config["enabled"] and not previous["enabled"]:
                config["capture_started_at"] = now()
            db.execute("INSERT INTO learning_settings VALUES(1,?) ON CONFLICT(id) DO UPDATE SET body=excluded.body", (json.dumps(config),))
            audit(db, "settings.updated", actor=actor)
            result = {}
            for job in db.execute("SELECT j.*,c.project_id FROM learning_jobs j JOIN learning_conversations c ON c.session_id=j.session_id WHERE j.status='running'").fetchall():
                is_excluded = excluded(config, job["session_id"], job["project_id"])
                if is_excluded or not config["enabled"] or config["paused"] or not (config["memory_enabled"] or config["improvements_enabled"]):
                    result.setdefault("background_generation_cancel_requests", []).append(job["request_id"])
                    db.execute("UPDATE learning_jobs SET status=?,request_id='',due=?,updated_at=? WHERE id=?",
                               ("cancelled" if is_excluded else "queued", now() + 15, now(), job["id"]))
            return {**dashboard(db), **result}
        if action == "learning.analyze_now":
            session = str(body.get("session_id", ""))
            if not db.execute("SELECT 1 FROM learning_conversations WHERE session_id=?", (session,)).fetchone():
                raise ValueError("No captured evidence for this chat; enable learning before its next turn")
            enqueue(db, session, now())
            db.execute("UPDATE learning_conversations SET last_activity=0 WHERE session_id=?", (session,))
            audit(db, "analysis.requested", session, actor)
            return dashboard(db)
        if action == "learning.job":
            return job_action(db, body, actor)
        if action == "learning.review":
            return review(db, {**body, "memory_provider_app_id": selected_memory_provider(payload)}, actor)
        raise ValueError("Unknown learning operation")


def dashboard(db):
    config = settings(db)
    runtime = db.execute("SELECT ready FROM learning_runtime_state WHERE id=1").fetchone()
    jobs = [dict(x) for x in db.execute("SELECT * FROM learning_jobs ORDER BY created_at DESC LIMIT 100")]
    for job in jobs:
        job.pop("input_json", None)
        job.pop("request_id", None)
        job.pop("output_text", None)
    items = [dict(x) for x in db.execute("""SELECT * FROM learning_items
        ORDER BY CASE WHEN status IN ('pending','accepted','checking','saving','undoing') THEN 0 ELSE 1 END,
        updated_at DESC LIMIT 200""")]
    for item in items:
        item["evidence"] = json.loads(item["evidence"])
        item["details"] = json.loads(item["details"])
        item.pop("operation_id", None)
    implementations.attach_tickets(db, items)
    from datetime import UTC, datetime
    day = datetime.now(UTC).date().isoformat()
    spent = daily_consumption(db, day)
    counts = {"pending_memory": 0, "pending_improvements": 0, "queued": 0, "running": 0, "failed": 0}
    for row in db.execute("SELECT kind,COUNT(*) AS total FROM learning_items WHERE status='pending' GROUP BY kind"):
        counts["pending_memory" if row["kind"] == "memory" else "pending_improvements"] = row["total"]
    for row in db.execute("SELECT status,COUNT(*) AS total FROM learning_jobs WHERE status IN ('queued','running','failed') GROUP BY status"):
        counts[row["status"]] = row["total"]
    counts["budget_waiting"] = db.execute("SELECT COUNT(*) FROM learning_jobs WHERE status='queued' AND error=?", (BUDGET_WAIT_REASON,)).fetchone()[0]
    for kind in ("memory", "improvement"):
        counts["open_" + kind] = db.execute("""SELECT COUNT(*) FROM learning_items i LEFT JOIN learning_implementations t ON t.item_id=i.id
            WHERE i.kind=? AND i.status NOT IN ('rejected','implemented','undone') AND
            (i.status IN ('pending','accepted','checking','saving','undoing') OR t.status IN ('queued','launching','running','stopping','awaiting_review','failed','cancelled'))""", (kind,)).fetchone()[0]
    conversations = [dict(x) for x in db.execute("""SELECT c.session_id,c.project_id,c.last_activity,
        (SELECT input_text FROM learning_exchanges e WHERE e.session_id=c.session_id ORDER BY seq LIMIT 1) AS label
        FROM learning_conversations c ORDER BY last_activity DESC LIMIT 100""")]
    for conversation in conversations:
        conversation["label"] = " ".join((conversation["label"] or "").split())[:80] or "Chat " + conversation["session_id"][:8]
    return {"settings": config, "jobs": jobs, "items": items, "daily_tokens_reserved_or_used": spent,
            "runtime_ready": bool(runtime and runtime[0]),
            "concurrency": 1, "counts": counts, "conversations": conversations,
            "audit": [dict(x) for x in db.execute("SELECT * FROM learning_audit ORDER BY id DESC LIMIT 50")]}


def selected_memory_provider(payload):
    dependencies = payload.get("app_dependencies", {}).get("dependencies", [])
    selected = next((x.get("selected_provider_app_ids", []) for x in dependencies if x.get("alias") == "learning-memory"), [])
    return selected[0] if selected else ""


def job_action(db, body, actor):
    job = db.execute("SELECT * FROM learning_jobs WHERE id=?", (body.get("job_id", ""),)).fetchone()
    if not job:
        raise ValueError("Analysis not found")
    command = body.get("command")
    if command == "inspect":
        return {"job": {**dict(job), "request_id": "", "input": json.loads(job["input_json"])}}
    if command == "cancel" and job["status"] in {"running", "queued"}:
        db.execute("UPDATE learning_jobs SET status='cancelled',updated_at=? WHERE id=?", (now(), job["id"]))
        audit(db, "analysis.cancelled", job["id"], actor)
        return {"background_generation_cancel_requests": [job["request_id"]] if job["request_id"] else []}
    if command == "retry" and job["status"] in {"failed", "cancelled"}:
        db.execute("UPDATE learning_jobs SET status='queued',attempts=0,request_id='',due=?,updated_at=? WHERE id=?", (now(), now(), job["id"]))
        audit(db, "analysis.retry", job["id"], actor)
        return {}
    raise ValueError("Invalid analysis transition")


def review(db, body, actor):
    item = db.execute("SELECT * FROM learning_items WHERE id=?", (body.get("item_id", ""),)).fetchone()
    if not item:
        raise ValueError("Candidate not found")
    command = body.get("command")
    details = json.loads(item["details"])
    if item["status"] == "rejected":
        raise ValueError("This candidate was dismissed")
    if command == "reject" and db.execute("SELECT 1 FROM learning_implementations WHERE item_id=? AND status NOT IN ('cancelled','failed')", (item["id"],)).fetchone():
        raise ValueError("Stop the work chat before rejecting the ticket")
    if item["kind"] == "memory" and command in {"retry", "stop"}:
        return implementations.ticket_action(db, item, command, actor)
    if item["status"] in {"saving", "undoing", "checking"}:
        raise ValueError("This candidate has an operation in progress")
    if item["kind"] == "memory" and command == "approve" and item["status"] == "accepted":
        return implementations.queue_item(db, item, actor)
    if item["kind"] == "memory" and command == "start" and item["status"] == "accepted":
        return implementations.queue_item(db, item, actor)
    if command == "edit" and db.execute("SELECT 1 FROM learning_implementations WHERE item_id=? AND status IN ('queued','launching','running','stopping')", (item["id"],)).fetchone():
        raise ValueError("Stop the work chat before editing an approved ticket")
    if item["kind"] == "improvement":
        if command in {"accept", "start"}:
            return implementations.queue_item(db, item, actor)
        if command in {"retry", "stop", "implemented"} and db.execute("SELECT 1 FROM learning_implementations WHERE item_id=?", (item["id"],)).fetchone():
            return implementations.ticket_action(db, item, command, actor)
    if command in {"edit", "approve"} and item["status"] == "pending":
        title, text = body.get("title", item["title"]), body.get("body", item["body"])
        if not isinstance(title, str) or not title.strip() or len(title) > 240 or not isinstance(text, str) or not text.strip() or len(text) > 4000:
            raise ValueError("Invalid candidate text")
        db.execute("UPDATE learning_items SET title=?,body=?,updated_at=? WHERE id=?", (title, text, now(), item["id"]))
        item = db.execute("SELECT * FROM learning_items WHERE id=?", (item["id"],)).fetchone()
    if command == "edit" and item["status"] == "pending":
        pass
    elif command == "approve" and item["kind"] == "memory" and item["status"] == "pending":
        if not item["provider_id"]:
            provider = body.get("memory_provider_app_id", "")
            if not provider:
                raise ValueError("Choose and save a Memory provider in Settings before approving this candidate")
            db.execute("UPDATE learning_items SET provider_id=? WHERE id=?", (provider, item["id"]))
            item = db.execute("SELECT * FROM learning_items WHERE id=?", (item["id"],)).fetchone()
        target = str(body.get("target_node_id", ""))
        matches = details.get("memory_matches", [])
        if matches and not target and body.get("confirm_new") is not True:
            raise ValueError("Choose an existing Memory node or explicitly create a separate fact")
        if target and target not in {x["id"] for x in matches}:
            raise ValueError("Choose a matching Memory node")
        details["target_node_id"] = target
        db.execute("UPDATE learning_items SET details=? WHERE id=?", (json.dumps(details), item["id"]))
        return implementations.queue_item(db, item, actor)
    elif command == "undo" and item["kind"] == "memory" and item["status"] == "saved":
        if not details.get("node_created"):
            raise ValueError("This save attached evidence to an existing node; manage its sources in Memory")
        token = "undo:" + item["id"]
        db.execute("UPDATE learning_items SET status='undoing',operation_id=?,updated_at=? WHERE id=?", (token, now(), item["id"]))
        return {"dependency_backend_requests": [dependency_request(item["id"], "learning.memory_undone", {
            "action": "delete_node", "node_id": item["node_id"], "expected_updated_at": details.get("node_updated_at", ""),
            "reason": "conversation_learning_undo", "actor_id": actor}, operation_id=token, provider_id=item["provider_id"])]}
    elif command in {"reject", "accept", "implemented"}:
        allowed = {"reject": {"pending", "accepted"}, "accept": {"pending"}, "implemented": {"accepted"}}
        if item["status"] not in allowed[command] or (command != "reject" and item["kind"] != "improvement"):
            raise ValueError("Invalid review transition")
        status = {"reject": "rejected", "accept": "accepted", "implemented": "implemented"}[command]
        db.execute("UPDATE learning_items SET status=?,updated_at=? WHERE id=?", (status, now(), item["id"]))
        if command == "reject":
            db.execute("UPDATE learning_implementations SET status='cancelled',updated_at=? WHERE item_id=?", (now(), item["id"]))
    else:
        raise ValueError("Invalid review transition")
    audit(db, "review." + command, item["id"], actor)
    return {}


def cleanup(root, session_ids):
    cancellations = []
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
            for item in db.execute("SELECT id,evidence FROM learning_items WHERE status IN ('checking','pending','rejected')").fetchall():
                original = json.loads(item["evidence"])
                remaining = [x for x in original if x["session_id"] != session]
                if len(remaining) != len(original):
                    db.execute("UPDATE learning_items SET evidence=?,status=CASE WHEN ?=0 THEN 'rejected' ELSE status END,updated_at=? WHERE id=?",
                               (json.dumps(remaining), len(remaining), now(), item["id"]))
    return {"background_generation_cancel_requests": cancellations}
