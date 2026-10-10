"""Resumable, bounded flag sweeps over an IMAP folder's cached UIDs."""

import json
import re

from database import connect
from provider_errors import ProviderError


FLAG_BATCH_SIZE = 200


def prepare_flag_sweep(data_root, connection_id, folder, state, *, restart):
    progress = state.get("flags")
    if progress and (not progress["complete"] or not restart):
        return
    prefix = f"{folder['name']}:{state['uidvalidity']}:"
    with connect(data_root) as db:
        upper = db.execute("""SELECT MAX(CAST(substr(provider_message_id, ?) AS INTEGER))
        FROM messages JOIN threads ON threads.id=messages.thread_id
        WHERE connection_id=? AND substr(provider_message_id, 1, ?)=?""",
                           (len(prefix) + 1, connection_id, len(prefix), prefix)).fetchone()[0]
    state["flags"] = {"after_uid": 0, "through_uid": upper or 0, "complete": not upper}


def refresh_flag_page(client, data_root, connection_id, folder, state, budget, limit):
    from .imap_sync import aggregate_thread
    from .imap_smtp import _select_folder
    progress = state["flags"]
    prefix = f"{folder['name']}:{state['uidvalidity']}:"
    limit = min(limit, FLAG_BATCH_SIZE, budget.remaining)
    with connect(data_root) as db:
        rows = db.execute("""SELECT messages.id, thread_id, messages.labels_json,
        CAST(substr(provider_message_id, ?) AS INTEGER) AS uid
        FROM messages JOIN threads ON threads.id=messages.thread_id
        WHERE connection_id=? AND substr(provider_message_id, 1, ?)=?
        AND uid>? AND uid<=? ORDER BY uid LIMIT ?""",
                          (len(prefix) + 1, connection_id, len(prefix), prefix,
                           progress["after_uid"], progress["through_uid"], limit + 1)).fetchall()
    batch = rows[:limit]
    if not batch:
        progress["complete"] = True
        return 0
    selected = {row["uid"]: row for row in batch}
    _select_folder(client, folder["name"], expected_uidvalidity=state["uidvalidity"])
    budget.charge(len(batch))
    typ, data = client.uid("FETCH", ",".join(str(uid) for uid in selected), "(UID FLAGS)")
    if str(typ).upper() != "OK":
        raise ProviderError("IMAP flag refresh failed; flag cursor was preserved", code="provider_protocol_error")
    with connect(data_root) as db:
        affected = set()
        for item in data or []:
            text = item[0] if isinstance(item, tuple) else item
            text = text.decode("ascii", errors="replace") if isinstance(text, bytes) else str(text)
            uid = re.search(r"UID\s+(\d+)", text, re.I)
            match = re.search(r"FLAGS\s+\(([^)]*)\)", text, re.I)
            if not match or not uid or int(uid[1]) not in selected:
                continue
            row = selected[int(uid[1])]
            labels = {folder["canonical"], folder["type"]}
            flags = {flag.casefold() for flag in match[1].split()}
            if "\\seen" not in flags:
                labels.add("unread")
            if "\\flagged" in flags:
                labels.add("starred")
            if labels == set(json.loads(row["labels_json"])):
                continue
            db.execute("UPDATE messages SET labels_json=? WHERE id=?", (json.dumps(sorted(labels)), row["id"]))
            affected.add(row["thread_id"])
        for thread_id in affected:
            aggregate_thread(db, thread_id)
    progress.update(after_uid=batch[-1]["uid"], complete=len(rows) <= limit)
    return len(batch)
