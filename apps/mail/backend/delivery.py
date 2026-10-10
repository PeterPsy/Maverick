"""Persist delivery outcomes before any best-effort cache maintenance."""

from database import connect, now_timestamp
import json


EDITABLE_DRAFT_STATES = {"draft", "failed"}


def require_sendable(draft):
    if draft["status"] not in EDITABLE_DRAFT_STATES:
        raise ValueError(f"Draft send approval is already used or delivery is in progress (state `{draft['status']}`); check the recorded delivery outcome")


def claim_send(db, draft_id, preview):
    """Called in the same transaction that consumes the approval."""
    result = db.execute(
        """UPDATE drafts SET status = 'sending', send_started_at = ?, send_result_json = '{}'
        WHERE id = ? AND status IN ('draft', 'failed') AND updated_at = ?""",
        (now_timestamp(), draft_id, preview.get("draft_updated_at")),
    )
    if result.rowcount != 1:
        raise ValueError("Draft changed or send is already in progress/completed; approval was not consumed")


def record_delivery(data_root, draft_id, state, *, provider_message_id="", thread_id="", accepted=None, refused=None, error_code=""):
    now = now_timestamp()
    result = {
        "status": state, "sent": state == "sent",
        "provider_message_id": provider_message_id, "thread_id": thread_id,
        "accepted_recipients": accepted or [], "refused_recipients": refused or {},
    }
    if error_code:
        result["error_code"] = error_code
    with connect(data_root) as db:
        db.execute(
            """UPDATE drafts SET status = ?, dirty = ?, sent_at = ?, updated_at = ?, send_result_json = ?
            WHERE id = ? AND status = 'sending'""",
            (state, 0 if state in {"sent", "partially_sent"} else 1,
             now if state in {"sent", "partially_sent"} else None, now,
             json.dumps(result, ensure_ascii=True), draft_id),
        )
    return result


def envelope_recipients(draft):
    return list(dict.fromkeys(str(item["email"]) for field in ("to", "cc", "bcc") for item in draft.get(field, []) if item.get("email")))


def finish_local_delivery(result, *operations):
    warnings = []
    for name, operation in operations:
        try:
            operation()
        except Exception:
            warnings.append(name)
    if warnings:
        result["local_warnings"] = warnings
    return result
