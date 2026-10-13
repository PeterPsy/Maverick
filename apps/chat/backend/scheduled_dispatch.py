"""Persisted stop fences shared by dispatch, recovery and launch callbacks."""


def request_stopped(db, chat, request):
    if chat["deleted"] or request["status"] == "cancelled":
        return True
    if request["kind"] != "block":
        return False
    run = db.execute("SELECT status,finished_at FROM scheduled_runs WHERE id=?", (request["run_id"],)).fetchone()
    step = db.execute("SELECT request_id FROM scheduled_steps WHERE run_id=? AND node_id=?",
                      (request["run_id"], request["node_id"])).fetchone()
    return bool(chat["paused"] or not run or run["status"] == "paused" or run["finished_at"] is not None
                or not step or step["request_id"] != request["id"])


def cancel_unsubmitted_request(db, request):
    db.execute("UPDATE scheduled_requests SET status='cancelled' WHERE id=?", (request["id"],))
    db.execute("""UPDATE scheduled_steps SET status='cancelled'
        WHERE run_id=? AND node_id=? AND request_id=? AND status='running'""",
        (request["run_id"], request["node_id"], request["id"]))
