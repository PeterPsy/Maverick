"""Explicit run transitions; checkpoints never advance from turn completion alone."""

import json

from scheduled_runtime import ACTIVE, create_run, dispatch_ready, settle_run
from scheduled_store import now, open_run


def interrupts(db, chat_id, *, blocks_only=True):
    return [{"turn_id": row[0], "reason": "Scheduled chat paused or cancelled"} for row in db.execute(
        "SELECT turn_id FROM scheduled_requests WHERE chat_id=? AND status IN ('launching','running') AND turn_id!=''" +
        (" AND kind='block'" if blocks_only else ""), (chat_id,))]


def control(db, chat, body):
    action, run = body["action"], open_run(db, chat["id"])
    result = {"_scheduled_changed": True}
    if action in {"scheduled.pause", "scheduled.delete", "scheduled.cancel"}:
        result["runtime_turn_interrupt_requests"] = interrupts(db, chat["id"], blocks_only=action != "scheduled.delete")
        queued = db.execute("SELECT id,run_id,node_id FROM scheduled_requests WHERE chat_id=? AND status='queued'" +
                            (" AND kind='block'" if action != "scheduled.delete" else ""), (chat["id"],)).fetchall()
        for request in queued:
            db.execute("UPDATE scheduled_requests SET status='cancelled' WHERE id=?", (request["id"],))
            db.execute("UPDATE scheduled_steps SET status='cancelled' WHERE run_id=? AND node_id=? AND request_id=?",
                       (request["run_id"], request["node_id"], request["id"]))
        if action == "scheduled.pause":
            db.execute("UPDATE scheduled_chats SET paused=1,revision=revision+1,updated_at=? WHERE id=?", (now(), chat["id"]))
            if run:
                db.execute("UPDATE scheduled_runs SET status='paused' WHERE id=?", (run["id"],))
        elif action == "scheduled.delete":
            db.execute("UPDATE scheduled_chats SET deleted=1,paused=1,revision=revision+1 WHERE id=?", (chat["id"],))
        if action != "scheduled.pause" and run:
            db.execute("UPDATE scheduled_runs SET status='cancelled',finished_at=? WHERE id=?", (now(), run["id"]))
            db.execute("UPDATE scheduled_steps SET status='cancelled' WHERE run_id=? AND status IN ('pending','running')", (run["id"],))
        return result
    if action == "scheduled.resume":
        from scheduled_validation import next_due
        db.execute("UPDATE scheduled_chats SET paused=0,next_due=?,revision=revision+1,updated_at=? WHERE id=?",
                   (next_due(json.loads(chat["config"])["schedule"], now()), now(), chat["id"]))
        if run:
            db.execute("UPDATE scheduled_runs SET status='running' WHERE id=?", (run["id"],))
            settle_run(db, chat, run["id"])
        return result
    if chat["paused"]:
        raise ValueError("Resume this scheduled chat first")
    if action == "scheduled.run":
        run = create_run(db, chat)
        if json.loads(chat["config"])["schedule"]["frequency"] == "once":
            db.execute("UPDATE scheduled_chats SET next_due=NULL WHERE id=?", (chat["id"],))
    elif action == "scheduled.continue":
        if not run or body.get("run_id") != run["id"]:
            raise ValueError("The run has changed; reload before confirming checkpoints")
        ids = body.get("node_ids")
        if not isinstance(ids, list) or not ids or len(ids) > 64 or any(not isinstance(node, str) for node in ids):
            raise ValueError("Choose the checkpoint blocks to confirm")
        for node_id in set(ids):
            step = db.execute("SELECT status FROM scheduled_steps WHERE run_id=? AND node_id=?", (run["id"], node_id)).fetchone()
            if not step or step[0] not in {"checkpoint", "completed"}:
                raise ValueError("Only successful checkpoints can be confirmed")
            db.execute("UPDATE scheduled_steps SET status='completed' WHERE run_id=? AND node_id=?", (run["id"], node_id))
        settle_run(db, chat, run["id"])
        run = db.execute("SELECT * FROM scheduled_runs WHERE id=?", (run["id"],)).fetchone()
    elif action == "scheduled.retry":
        if not run or body.get("run_id") != run["id"]:
            raise ValueError("The run has changed; reload before retrying")
        step = db.execute("SELECT * FROM scheduled_steps WHERE run_id=? AND node_id=?", (run["id"], body.get("node_id", ""))).fetchone()
        if not step or step["status"] not in {"failed", "cancelled"}:
            raise ValueError("Only failed or cancelled blocks can be retried")
        request = db.execute("SELECT * FROM scheduled_requests WHERE id=?", (step["request_id"],)).fetchone()
        if request and request["status"] in ACTIVE:
            raise ValueError("Wait for the previous turn to stop before retrying")
        if request and not request["turn_id"]:
            # An unconfirmed launch keeps its original key and payload, never a fresh turn.
            db.execute("UPDATE scheduled_requests SET status='launching',updated_at=? WHERE id=?", (now(), request["id"]))
            db.execute("UPDATE scheduled_steps SET status='running' WHERE run_id=? AND node_id=?", (run["id"], step["node_id"]))
            result["runtime_session_requests"] = [json.loads(request["request_json"])]
        else:
            db.execute("UPDATE scheduled_steps SET status='pending',request_id='' WHERE run_id=? AND node_id=?", (run["id"], step["node_id"]))
        db.execute("UPDATE scheduled_runs SET status='running' WHERE id=?", (run["id"],))
        run = db.execute("SELECT * FROM scheduled_runs WHERE id=?", (run["id"],)).fetchone()
    else:
        raise ValueError("Unknown scheduled-chat control")
    if run and run["finished_at"] is None:
        result.setdefault("runtime_session_requests", []).extend(dispatch_ready(db, chat, run))
    return result
