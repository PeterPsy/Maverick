"""Durable learning tickets with bounded concurrency and visible Chat runtime turns."""

import json

from learning_implementation_context import implementation_request
from learning_store import audit, connection, new_id, now, settings
from learning_projects import learning_projects
from learning_reconciliation import current_review
from learning_review_schema import POLICY_VERSION

ACTIVE = {"launching", "running", "stopping"}
TERMINAL = {"completed": "awaiting_review", "failed": "failed", "cancelled": "cancelled", "timed-out": "failed"}


def queue_item(db, item, actor):
    if item["kind"] not in {"improvement", "memory"} or item["status"] not in {"pending", "accepted"}:
        raise ValueError("Only proposed or accepted learning tickets can be started")
    if json.loads(item["details"]).get("policy_version") != POLICY_VERSION:
        raise ValueError("This candidate needs a fresh review under the current criteria before approval")
    existing = db.execute("SELECT * FROM learning_implementations WHERE item_id=?", (item["id"],)).fetchone()
    if not existing:
        db.execute("""INSERT INTO learning_implementations(item_id,status,actor,created_at,updated_at)
            VALUES(?,'queued',?,?,?)""", (item["id"], actor, now(), now()))
        db.execute("UPDATE learning_items SET status='accepted',updated_at=? WHERE id=?", (now(), item["id"]))
        audit(db, "implementation.queued", item["id"], actor)
    return {"next_due_in_seconds": 1}


def ticket_action(db, item, command, actor):
    ticket = db.execute("SELECT * FROM learning_implementations WHERE item_id=?", (item["id"],)).fetchone()
    if not ticket:
        raise ValueError("Implementation ticket not found")
    if command == "retry" and ticket["status"] in {"failed", "cancelled", "awaiting_review"}:
        # A known chat is always reused; an unconfirmed launch replays its original key.
        request_id = new_id("implementation") if ticket["session_id"] else ticket["request_id"]
        request_json = "{}" if ticket["session_id"] else ticket["request_json"]
        db.execute("""UPDATE learning_implementations SET status='queued',request_id=?,request_json=?,
            turn_id='',error='',summary='',attempt=attempt+1,updated_at=? WHERE item_id=?""",
            (request_id, request_json, now(), item["id"]))
        if item["kind"] == "memory":
            db.execute("UPDATE learning_items SET status='accepted',updated_at=? WHERE id=?", (now(), item["id"]))
    elif command == "stop" and ticket["status"] in {"queued", "launching", "running", "stopping"}:
        status = "cancelled" if ticket["status"] == "queued" else "stopping"
        db.execute("UPDATE learning_implementations SET status=?,updated_at=? WHERE item_id=?", (status, now(), item["id"]))
    elif command == "implemented" and ticket["status"] == "awaiting_review":
        db.execute("UPDATE learning_implementations SET status='implemented',updated_at=? WHERE item_id=?", (now(), item["id"]))
        db.execute("UPDATE learning_items SET status='implemented',updated_at=? WHERE id=?", (now(), item["id"]))
    else:
        raise ValueError("Invalid implementation transition")
    audit(db, "implementation." + command, item["id"], actor)
    return {"next_due_in_seconds": 1}


def started(data_root, body):
    with connection(data_root, write=True) as db:
        ticket = db.execute("SELECT * FROM learning_implementations WHERE item_id=? AND request_id=?",
                            (body.get("item_id", ""), body.get("request_id", ""))).fetchone()
        if not ticket or ticket["status"] not in ACTIVE:
            return {"ignored": True}
        state = body.get("runtime_request_status", "failed")
        status = terminal_state(db, ticket["item_id"], state) if state in TERMINAL else ("running" if body.get("turn_id") else "launching")
        if ticket["status"] == "stopping" and state not in TERMINAL:
            status = "stopping"
        error = terminal_error(db, ticket["item_id"], state, body.get("error")) if state in TERMINAL else str(body.get("error") or "")[:500]
        if state == "reserving" and not body.get("turn_id"):
            status = "cancelled" if ticket["status"] == "stopping" else "failed"
            error = "Launch confirmation was lost. Retry reconciles the reserved request without creating another chat."
        db.execute("""UPDATE learning_implementations SET session_id=?,turn_id=?,status=?,error=?,updated_at=?
            WHERE item_id=?""", (body.get("runtime_session_id") or ticket["session_id"],
            body.get("turn_id") or ticket["turn_id"], status, error, now(), ticket["item_id"]))
        audit(db, "implementation." + status, ticket["item_id"])
    return {"_changed": True, "next_due_in_seconds": 1}


def runtime_event(data_root, body):
    """Consume every generated-chat event, including follow-ups, before learning capture."""
    with connection(data_root, write=True) as db:
        ticket = db.execute("""SELECT * FROM learning_implementations WHERE (session_id=? AND session_id!='')
            OR (request_id=? AND request_id!='')""", (body.get("runtime_session_id", ""), body.get("runtime_request_id", ""))).fetchone()
        if not ticket:
            return None
        event_id = body.get("runtime_event_id", "")
        if event_id and not db.execute("INSERT OR IGNORE INTO learning_implementation_events VALUES(?,?,?)", (event_id, ticket["item_id"], now())).rowcount:
            return {"ignored": True}
        if body.get("runtime_request_id") and body["runtime_request_id"] != ticket["request_id"]:
            return {"ignored": True}
        if not ticket["session_id"]:
            db.execute("UPDATE learning_implementations SET session_id=?,turn_id=? WHERE item_id=?", (body.get("runtime_session_id", ""), body.get("turn_id", ""), ticket["item_id"]))
            ticket = db.execute("SELECT * FROM learning_implementations WHERE item_id=?", (ticket["item_id"],)).fetchone()
        action = body.get("action", "").removeprefix("runtime.turn.")
        if ticket["status"] in {"implemented", "cancelled"}:
            return {"ignored": True}
        if action == "queued":
            if ticket["turn_id"] == body.get("turn_id") and ticket["status"] not in ACTIVE:
                return {"ignored": True}
            status = "stopping" if ticket["status"] == "stopping" else "running"
            db.execute("UPDATE learning_implementations SET status=?,turn_id=?,updated_at=? WHERE item_id=?",
                       (status, body.get("turn_id", ""), now(), ticket["item_id"]))
        elif action in TERMINAL and body.get("turn_id") == ticket["turn_id"] and ticket["status"] in ACTIVE:
            db.execute("UPDATE learning_implementations SET status=?,summary=?,error=?,updated_at=? WHERE item_id=?",
                       (terminal_state(db, ticket["item_id"], action), str(body.get("output_text") or "")[:16_000],
                        terminal_error(db, ticket["item_id"], action, body.get("failure_reason", "")), now(), ticket["item_id"]))
        else:
            return {"ignored": True}
        audit(db, "implementation.turn." + action, ticket["item_id"])
    return {"_changed": True, "next_due_in_seconds": 1}


def tick(data_root, body):
    projects, projects_changed = learning_projects(data_root, ensure=True)
    result = {"next_due_in_seconds": 5, "_projects_changed": projects_changed}
    with connection(data_root, write=True) as db:
        ready = "runtime_request_states" in body
        previous = db.execute("SELECT ready FROM learning_runtime_state WHERE id=1").fetchone()
        if previous is None or bool(previous[0]) != ready:
            db.execute("INSERT INTO learning_runtime_state VALUES(1,?) ON CONFLICT(id) DO UPDATE SET ready=excluded.ready", (int(ready),))
            result["_changed"] = True
        if not ready:
            return result
        for state in body.get("runtime_request_states", []):
            ticket = db.execute("SELECT * FROM learning_implementations WHERE request_id=? AND request_id!='' AND status IN ('launching','running','stopping')", (state.get("request_id", ""),)).fetchone()
            if not ticket or not state.get("session_id"):
                continue
            if not ticket["session_id"] or not ticket["turn_id"]:
                db.execute("UPDATE learning_implementations SET session_id=?,turn_id=?,status=?,updated_at=? WHERE item_id=?",
                    (state["session_id"], state.get("turn_id", ""), "stopping" if ticket["status"] == "stopping" else "running", now(), ticket["item_id"]))
                result["_changed"] = True
            if state.get("status") in TERMINAL and (not ticket["turn_id"] or ticket["turn_id"] == state.get("turn_id")):
                db.execute("UPDATE learning_implementations SET status=?,error=?,updated_at=? WHERE item_id=?", (terminal_state(db, ticket["item_id"], state["status"]), terminal_error(db,ticket["item_id"],state["status"],ticket["error"]), now(), ticket["item_id"]))
                result["_changed"] = True
        if body.get("action") == "backend.recovery":
            return result
        active = db.execute("""SELECT t.*,i.kind FROM learning_implementations t JOIN learning_items i ON i.id=t.item_id
            WHERE t.status IN ('launching','running','stopping') ORDER BY t.created_at""").fetchall()
        for running in active:
            ticket = running
            if ticket["status"] == "stopping" and ticket["turn_id"]:
                result.setdefault("runtime_turn_interrupt_requests", []).append({"turn_id": ticket["turn_id"], "reason": "Implementation stopped from Settings"})
            elif (ticket["status"] == "launching" or not ticket["turn_id"]) and now() - ticket["updated_at"] > 30:
                request = json.loads(ticket["request_json"])
                if request:
                    result.setdefault("runtime_session_requests", []).append(request)
                    db.execute("UPDATE learning_implementations SET updated_at=? WHERE item_id=?", (now(), ticket["item_id"]))
        limits = {"memory": 1, "improvement": settings(db)["improvement_concurrency"]}
        for kind, limit in limits.items():
            slots = max(0, limit - sum(ticket["kind"] == kind for ticket in active))
            queued = db.execute("""SELECT t.* FROM learning_implementations t JOIN learning_items i ON i.id=t.item_id
                WHERE t.status='queued' AND i.kind=? ORDER BY t.created_at,t.item_id""", (kind,)).fetchall()
            for ticket in queued:
                if not slots:
                    break
                item = db.execute("SELECT * FROM learning_items WHERE id=?", (ticket["item_id"],)).fetchone()
                if not current_review(db, item, body.get("busy_runtime_session_ids", [])):
                    from learning_queue import enqueue
                    for source in db.execute("SELECT session_id FROM learning_item_sources WHERE item_id=?", (item["id"],)).fetchall():
                        enqueue(db, source[0], now() + settings(db)["idle_seconds"], reschedule=False)
                    continue
                ticket = dict(ticket)
                ticket["request_id"] = ticket["request_id"] or new_id("implementation")
                request = json.loads(ticket["request_json"]) or implementation_request(db, item, ticket, project_id=projects[kind])
                db.execute("UPDATE learning_implementations SET status='launching',request_id=?,request_json=?,updated_at=? WHERE item_id=?",
                           (ticket["request_id"], json.dumps(request), now(), ticket["item_id"]))
                audit(db, "implementation.launching", ticket["item_id"])
                result.setdefault("runtime_session_requests", []).append(request)
                slots -= 1
                result["_changed"] = True
        if not active and not result.get("runtime_session_requests"):
            result["next_due_in_seconds"] = 30
        return result


def terminal_state(db, item_id, state):
    item = db.execute("SELECT kind,status FROM learning_items WHERE id=?", (item_id,)).fetchone()
    if item["kind"] == "memory":
        return "saved" if item["status"] == "saved" else "failed" if state == "completed" else TERMINAL[state]
    return TERMINAL[state]


def terminal_error(db, item_id, state, failure=""):
    if state == "completed" and terminal_state(db, item_id, state) == "failed":
        return "The agent ended without a verified Memory save. Inspect the work chat and retry."
    return "" if state == "completed" else str(failure or state)[:500]


def attach_tickets(db, items):
    tickets = {row["item_id"]: dict(row) for row in db.execute("SELECT * FROM learning_implementations")}
    for item in items:
        ticket = tickets.get(item["id"])
        if ticket:
            for key in ("request_json", "request_id"):
                ticket.pop(key, None)
            item["implementation"] = ticket
