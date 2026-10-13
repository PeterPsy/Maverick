"""Reconcile app-owned links after trusted Core runtime deletion."""

from scheduled_runtime import ACTIVE, complete_request
from scheduled_store import connection


def cleanup(data_root, session_ids):
    if not isinstance(session_ids, list) or len(session_ids) > 5000 or any(not isinstance(value, str) or len(value) > 240 for value in session_ids):
        raise ValueError("Invalid runtime cleanup session ids")
    changed = False
    with connection(data_root, write=True) as db:
        for session_id in set(session_ids):
            if not session_id:
                continue
            requests = db.execute("SELECT * FROM scheduled_requests WHERE session_id=?", (session_id,)).fetchall()
            for request in requests:
                chat = db.execute("SELECT * FROM scheduled_chats WHERE id=?", (request["chat_id"],)).fetchone()
                if request["status"] in ACTIVE:
                    complete_request(db, chat, request, "cancelled", request["output"], "The work chat was deleted", "", request["turn_id"])
                if request["kind"] == "message":
                    db.execute("UPDATE scheduled_requests SET status='failed',error='The management chat was deleted. Start a new chat.' WHERE id=?", (request["id"],))
                db.execute("UPDATE scheduled_requests SET session_id='' WHERE id=?", (request["id"],))
                changed = True
            if db.execute("UPDATE scheduled_chats SET chat_session_id='' WHERE chat_session_id=?", (session_id,)).rowcount:
                changed = True
    return {"_scheduled_changed": changed}
