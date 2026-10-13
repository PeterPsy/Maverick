"""Background recurrence, idempotent replay and restart reconciliation."""

import json

from scheduled_dispatch import cancel_unsubmitted_request, request_stopped
from scheduled_runtime import TERMINAL, complete_request, create_run, dispatch_ready, runtime_event, settle_run
from scheduled_store import connection, now, open_run
from scheduled_validation import next_due


def tick(data_root, body):
    result = {"next_due_in_seconds": 30}
    with connection(data_root, write=True) as db:
        for event in body.get("recent_terminal_exchanges", []):
            update = runtime_event(db, event)
            if update:
                merge(result, update)
        for state in body.get("runtime_request_states", []):
            request = db.execute("SELECT * FROM scheduled_requests WHERE id=? AND status IN ('queued','launching','running','cancelled')", (state.get("request_id", ""),)).fetchone()
            if not request or not state.get("session_id") or request["turn_id"] and request["turn_id"] != state.get("turn_id"):
                continue
            if request["status"] == "cancelled" and request["turn_id"] and state.get("status") in TERMINAL:
                continue
            db.execute("UPDATE scheduled_requests SET session_id=?,turn_id=? WHERE id=?", (state["session_id"], state.get("turn_id", ""), request["id"]))
            chat = db.execute("SELECT * FROM scheduled_chats WHERE id=?", (request["chat_id"],)).fetchone()
            stopped = request_stopped(db, chat, request)
            if stopped:
                if state.get("status") in TERMINAL:
                    status = "cancelled" if state["status"] == "completed" else state["status"]
                    complete_request(db, chat, request, status, "", "Scheduled task stopped", state["session_id"], state.get("turn_id", ""))
                elif state.get("turn_id"):
                    result.setdefault("runtime_turn_interrupt_requests", []).append({"turn_id": state["turn_id"], "reason": "Scheduled task stopped"})
                result["_scheduled_changed"] = True
                continue
            if request["kind"] == "message":
                db.execute("UPDATE scheduled_chats SET chat_session_id=? WHERE id=?", (state["session_id"], chat["id"]))
            if state.get("turn_id"):
                db.execute("UPDATE scheduled_requests SET status='running' WHERE id=?", (request["id"],))
            if state.get("status") in TERMINAL and (state["status"] != "completed" or "output_text" in state):
                complete_request(db, chat, request, state["status"], state.get("output_text", request["output"]),
                                 state.get("failure_reason", request["error"]), state["session_id"], state.get("turn_id", ""))
                result["_scheduled_changed"] = True
        if "runtime_request_states" not in body:
            return result
        for request in db.execute("SELECT * FROM scheduled_requests WHERE status='queued' OR (status='launching' AND updated_at<?) LIMIT 8", (now() - 30,)).fetchall():
            chat = db.execute("SELECT * FROM scheduled_chats WHERE id=?", (request["chat_id"],)).fetchone()
            if request_stopped(db, chat, request):
                if not request["turn_id"]:
                    cancel_unsubmitted_request(db, request)
                    result["_scheduled_changed"] = True
                continue
            result.setdefault("runtime_session_requests", []).append(json.loads(request["request_json"]))
            db.execute("UPDATE scheduled_requests SET status='launching',updated_at=? WHERE id=?", (now(), request["id"]))
        for chat in db.execute("SELECT * FROM scheduled_chats WHERE deleted=0 AND paused=0 ORDER BY next_due,id").fetchall():
            run = open_run(db, chat["id"])
            if run is None and chat["next_due"] is not None and chat["next_due"] <= now():
                run = create_run(db, chat)
                db.execute("UPDATE scheduled_chats SET next_due=? WHERE id=?", (next_due(json.loads(chat["config"])["schedule"], now()), chat["id"]))
                result["_scheduled_changed"] = True
            if run:
                requests = dispatch_ready(db, chat, run)
                if requests:
                    result.setdefault("runtime_session_requests", []).extend(requests)
                    result["_scheduled_changed"] = True
                settle_run(db, chat, run["id"])
        interrupted = {item["turn_id"] for item in result.get("runtime_turn_interrupt_requests", [])}
        terminal_turns = {state.get("turn_id") for state in body["runtime_request_states"] if state.get("status") in TERMINAL}
        for request in db.execute("""SELECT r.turn_id FROM scheduled_requests r JOIN scheduled_chats c ON c.id=r.chat_id
            LEFT JOIN scheduled_runs run ON run.id=r.run_id WHERE r.status IN ('launching','running','cancelled') AND r.turn_id!=''
            AND (r.status='cancelled' OR c.deleted=1 OR (r.kind='block' AND (c.paused=1 OR run.finished_at IS NOT NULL)))"""):
            if request[0] not in interrupted | terminal_turns:
                result.setdefault("runtime_turn_interrupt_requests", []).append({"turn_id": request[0], "reason": "Scheduled task stopped"})
                interrupted.add(request[0])
        if db.execute("SELECT 1 FROM scheduled_requests WHERE status IN ('queued','launching','running') LIMIT 1").fetchone():
            result["next_due_in_seconds"] = 5
        due = db.execute("""SELECT MIN(next_due) FROM scheduled_chats c WHERE paused=0 AND deleted=0
            AND NOT EXISTS(SELECT 1 FROM scheduled_runs r WHERE r.chat_id=c.id AND r.finished_at IS NULL)""").fetchone()[0]
        if due is not None:
            result["next_due_in_seconds"] = max(1, min(result["next_due_in_seconds"], due - now()))
    return result


def merge(result, addition):
    for key, value in addition.items():
        if key.endswith("_requests") and isinstance(value, list):
            result.setdefault(key, []).extend(value)
        elif key == "next_due_in_seconds":
            result[key] = min(result.get(key, value), value)
        elif key.startswith("_"):
            result[key] = result.get(key, False) or value
        elif key != "ignored":
            result[key] = value
    return result
