"""Fair IMAP backfill, recent updates and UID inventory reconciliation."""

from collections import deque
import json
import re

from database import connect, now_timestamp
from .cache_reconciliation import remove_messages, remove_thread


def sync_mailbox(provider, data_root, connection_id, settings, password, *, max_total, continue_cursor, persist_cursor):
    from .imap_smtp import (_load_cursor, _imap_login, _list_folders, _cache_folders,
                            _uidvalidity, _uid_values, _fetch_message, _cache_message)
    cursor = _load_cursor(data_root, connection_id)
    states = cursor.get("folders", {}) if cursor.get("version") == 2 else {}
    queues = deque()
    synced = 0
    inventories = {}
    with provider._imap(settings) as client:
        _imap_login(client, str(settings["username"]), password)
        folders = _list_folders(client)
        _cache_folders(data_root, connection_id, folders)
        _reconcile_removed_folders(data_root, connection_id, {folder["name"] for folder in folders})
        for folder in folders:
            typ, _ = client.select(_quoted(folder["name"]), readonly=True)
            if str(typ).upper() != "OK":
                raise ValueError("IMAP folder could not be selected; sync cursor was preserved")
            validity = _uidvalidity(client)
            typ, data = client.uid("SEARCH", None, "ALL")
            if str(typ).upper() != "OK":
                raise ValueError("IMAP UID inventory failed; sync cursor was preserved")
            inventory = _uid_values(data)
            inventories[folder["name"]] = inventory
            _reconcile_folder(data_root, connection_id, folder["name"], validity, inventory)
            previous = states.get(folder["name"], {})
            initial = previous.get("uidvalidity") != validity or not previous
            state = {"uidvalidity": validity, "last_uid": 0, "backfill_before": max(inventory, default=0) + 1} if initial else dict(previous)
            high = int(state.get("last_uid") or 0)
            if initial:
                new = []
                history = list(reversed(inventory))
            else:
                typ, data = client.uid("SEARCH", None, "UID", f"{high + 1}:*")
                if str(typ).upper() != "OK":
                    raise ValueError("IMAP recent UID search failed; sync cursor was preserved")
                # IMAP ranges reverse when their lower bound exceeds the highest UID.
                new = sorted((uid for uid in _uid_values(data) if uid > high))
                history = [uid for uid in reversed(inventory) if uid < int(state.get("backfill_before") or 0)]
            queue = deque([(uid, "recent") for uid in new] + [(uid, "history") for uid in history if initial or continue_cursor])
            if initial:
                state["last_uid"] = max(inventory, default=0)
            states[folder["name"]] = state
            queues.append((folder, state, queue))
            _refresh_flags(client, data_root, connection_id, folder, validity, inventory)
        rotation = int(cursor.get("next_folder_index") or 0) % max(1, len(queues))
        queues.rotate(-rotation)
        next_folder_index = rotation
        # One message per folder per turn prevents a large Inbox starving Sent.
        while queues and synced < max_total:
            folder, state, queue = queues.popleft()
            if not queue:
                continue
            uid, kind = queue.popleft()
            typ, _ = client.select(_quoted(folder["name"]), readonly=True)
            if str(typ).upper() != "OK":
                raise ValueError("IMAP folder selection failed")
            raw, flags = _fetch_message(client, uid)
            if raw is None:
                raise ValueError("IMAP message fetch failed; sync cursor was preserved")
            _cache_message(data_root, connection_id, folder, uid, state["uidvalidity"], raw, flags=flags)
            if kind == "history":
                state["backfill_before"] = uid
            else:
                state["last_uid"] = max(uid, int(state["last_uid"]))
            synced += 1
            next_folder_index = (folders.index(folder) + 1) % len(folders)
            queues.append((folder, state, queue))
        has_more = any(queue for _, _, queue in queues)
        for folder in folders:
            state = states[folder["name"]]
            # The inventory already reconciles deleted historical UIDs.
            state["history_complete"] = not any(uid < int(state["backfill_before"]) for uid in inventories[folder["name"]])
            has_more |= not state["history_complete"]
    now = now_timestamp()
    with connect(data_root) as db:
        db.execute("""INSERT INTO sync_state(connection_id, last_sync_at, last_error, cursor, last_incremental_sync_at)
        VALUES (?, ?, '', ?, ?) ON CONFLICT(connection_id) DO UPDATE SET last_sync_at=excluded.last_sync_at,
        last_error='', cursor=excluded.cursor, last_incremental_sync_at=excluded.last_incremental_sync_at""",
                   (connection_id, now, json.dumps({"version": 2, "folders": states, "next_folder_index": next_folder_index}) if persist_cursor else json.dumps(cursor), now))
    return {"connection_id": connection_id, "synced_at": now, "synced_threads": synced,
            "synced_messages": synced, "has_more": has_more, "mode": "imap_smtp"}


def _quoted(folder):
    return '"' + folder.replace('\\', '\\\\').replace('"', '\\"') + '"'


def aggregate_thread(db, thread_id):
    rows = db.execute("SELECT * FROM messages WHERE thread_id = ? ORDER BY sent_at, id", (thread_id,)).fetchall()
    if not rows:
        remove_thread(db, thread_id)
        return
    labels = {label for row in rows for label in json.loads(row["labels_json"])}
    participants = {}
    for row in rows:
        for address in [json.loads(row["sender_json"]), *json.loads(row["recipients_json"]), *json.loads(row["cc_json"])]:
            if address.get("email"):
                participants[address["email"].casefold()] = address
    last = rows[-1]
    db.execute("UPDATE threads SET labels_json=?, unread=?, starred=?, participants_json=?, last_message_at=?, snippet=?, updated_at=? WHERE id=?",
               (json.dumps(sorted(labels)), int("unread" in labels), int("starred" in labels), json.dumps(list(participants.values())), last["sent_at"], last["body_preview"], now_timestamp(), thread_id))


def _reconcile_folder(data_root, connection_id, folder, validity, inventory):
    inventory = set(inventory)
    with connect(data_root) as db:
        rows = db.execute("SELECT messages.id, thread_id, provider_message_id FROM messages JOIN threads ON threads.id=messages.thread_id WHERE connection_id=?", (connection_id,)).fetchall()
        affected = set()
        for row in rows:
            name, old_validity, uid = row["provider_message_id"].rsplit(":", 2)
            if name == folder and (old_validity != validity or int(uid) not in inventory):
                remove_messages(db, [row["id"]])
                affected.add(row["thread_id"])
        for thread_id in affected:
            aggregate_thread(db, thread_id)


def _reconcile_removed_folders(data_root, connection_id, folder_names):
    with connect(data_root) as db:
        rows = db.execute("SELECT messages.id, thread_id, provider_message_id FROM messages JOIN threads ON threads.id=messages.thread_id WHERE connection_id=?", (connection_id,)).fetchall()
        affected = set()
        for row in rows:
            if row["provider_message_id"].rsplit(":", 2)[0] not in folder_names:
                remove_messages(db, [row["id"]])
                affected.add(row["thread_id"])
        for thread_id in affected:
            aggregate_thread(db, thread_id)
        for row in db.execute("SELECT id, provider_folder_id FROM folders WHERE connection_id=?", (connection_id,)).fetchall():
            if row["provider_folder_id"] not in folder_names:
                db.execute("DELETE FROM folders WHERE id=?", (row["id"],))


def _refresh_flags(client, data_root, connection_id, folder, validity, inventory):
    with connect(data_root) as db:
        rows = db.execute("SELECT messages.id, thread_id, provider_message_id FROM messages JOIN threads ON threads.id=messages.thread_id WHERE connection_id=?", (connection_id,)).fetchall()
    prefix = f"{folder['name']}:{validity}:"
    cached = {int(row["provider_message_id"][len(prefix):]): row for row in rows if row["provider_message_id"].startswith(prefix)}
    for start in range(0, len(cached), 200):
        batch = list(cached)[start:start + 200]
        typ, data = client.uid("FETCH", ",".join(str(uid) for uid in batch), "(UID FLAGS)")
        if str(typ).upper() != "OK":
            raise ValueError("IMAP flag refresh failed")
        with connect(data_root) as db:
            affected = set()
            for item in data or []:
                text = item[0] if isinstance(item, tuple) else item
                text = text.decode("ascii", errors="replace") if isinstance(text, bytes) else str(text)
                uid = re.search(r"UID\s+(\d+)", text, re.I)
                match = re.search(r"FLAGS\s+\(([^)]*)\)", text, re.I)
                if not match or not uid or int(uid[1]) not in cached:
                    continue
                row = cached[int(uid[1])]
                labels = {folder["canonical"], folder["type"]}
                flags = {flag.casefold() for flag in match[1].split()}
                if "\\seen" not in flags:
                    labels.add("unread")
                if "\\flagged" in flags:
                    labels.add("starred")
                db.execute("UPDATE messages SET labels_json=? WHERE id=?", (json.dumps(sorted(labels)), row["id"]))
                affected.add(row["thread_id"])
            for thread_id in affected:
                aggregate_thread(db, thread_id)
