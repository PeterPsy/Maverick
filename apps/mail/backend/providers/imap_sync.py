"""Fair IMAP backfill, recent updates and UID inventory reconciliation."""

from collections import deque
from dataclasses import dataclass
import json

from database import connect, now_timestamp
from .cache_reconciliation import remove_messages, remove_thread
from .imap_flags import prepare_flag_sweep, refresh_flag_page


MAX_FOLDER_SCANS = 10


@dataclass
class SyncBudget:
    remaining: int

    def charge(self, count):
        if count > self.remaining:
            raise ValueError("IMAP sync work budget exhausted")
        self.remaining -= count


def sync_mailbox(provider, data_root, connection_id, settings, password, *, budget, continue_cursor, persist_cursor):
    from .imap_smtp import (_load_cursor, _imap_login, _list_folders, _cache_folders,
                            _select_folder, _uid_values, _fetch_message, _cache_message)
    cursor = _load_cursor(data_root, connection_id)
    states = cursor.get("folders", {}) if cursor.get("version") == 2 else {}
    queues = deque()
    synced = 0
    flags_checked = 0
    initial_budget = budget.remaining
    inventories = {}
    with provider._imap(settings) as client:
        _imap_login(client, str(settings["username"]), password)
        folders = _list_folders(client)
        _cache_folders(data_root, connection_id, folders)
        _reconcile_removed_folders(data_root, connection_id, {folder["name"] for folder in folders})
        folder_names = {folder["name"] for folder in folders}
        states = {name: state for name, state in states.items() if name in folder_names}
        # A new sweep belongs to the whole mailbox, including folders visited
        # only by continuations. Keep an unfinished sweep across refreshes.
        if not continue_cursor and all(state.get("flags", {}).get("complete", False) for state in states.values()):
            states = {name: {key: value for key, value in state.items() if key != "flags"}
                      for name, state in states.items()}
        uninspected = set(cursor.get("inventory_remaining", [])) & folder_names
        uninspected.update(folder_names - states.keys())
        if not uninspected and not continue_cursor:
            uninspected = set(folder_names)
        rotation = int(cursor.get("next_folder_index") or 0) % max(1, len(folders))
        ordered = folders[rotation:] + folders[:rotation]
        selected_folders = ordered[:min(MAX_FOLDER_SCANS, budget.remaining)]
        next_folder_index = (rotation + len(selected_folders)) % max(1, len(folders))
        for folder in selected_folders:
            validity = _select_folder(client, folder["name"])
            typ, data = client.uid("SEARCH", None, "ALL")
            if str(typ).upper() != "OK":
                raise ValueError("IMAP UID inventory failed; sync cursor was preserved")
            inventory = _uid_values(data)
            inventories[folder["name"]] = inventory
            _reconcile_folder(data_root, connection_id, folder["name"], validity, inventory)
            previous = states.get(folder["name"], {})
            initial = previous.get("uidvalidity") != validity or not previous
            state = {"uidvalidity": validity, "last_uid": 0, "backfill_before": max(inventory, default=0) + 1} if initial else dict(previous)
            if state.get("flags"):
                state["flags"] = dict(state["flags"])
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
            state["recent_through_uid"] = max(new, default=state["last_uid"])
            states[folder["name"]] = state
            queues.append((folder, state, queue))
            prepare_flag_sweep(data_root, connection_id, folder, state, restart=False)
            uninspected.discard(folder["name"])
        body_pending = any(queue for _, _, queue in queues)
        flags_pending = any(not states[folder["name"]]["flags"]["complete"] for folder in selected_folders)
        body_limit = budget.remaining
        next_work = cursor.get("next_work", "messages")
        if body_pending and flags_pending:
            body_limit = int(next_work != "flags") if budget.remaining == 1 else (budget.remaining + 1) // 2
            next_work = "flags" if body_limit else "messages"
        # One message per folder per turn prevents a large Inbox starving Sent.
        while queues and synced < body_limit:
            folder, state, queue = queues.popleft()
            if not queue:
                continue
            uid, kind = queue.popleft()
            _select_folder(client, folder["name"], expected_uidvalidity=state["uidvalidity"])
            budget.charge(1)
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
        next_flag_folder = int(cursor.get("next_flag_folder_index") or 0)
        flag_folders = deque(sorted(selected_folders, key=lambda folder: (folders.index(folder) - next_flag_folder) % max(1, len(folders))))
        while flag_folders and budget.remaining:
            folder = flag_folders.popleft()
            state = states[folder["name"]]
            if state["flags"]["complete"]:
                continue
            flags_checked += refresh_flag_page(client, data_root, connection_id, folder, state, budget, budget.remaining)
            next_flag_folder = (folders.index(folder) + 1) % len(folders)
            if not state["flags"]["complete"]:
                flag_folders.append(folder)
        has_more = bool(uninspected) or any(queue for _, _, queue in queues)
        for folder in selected_folders:
            state = states[folder["name"]]
            # The inventory already reconciles deleted historical UIDs.
            state["history_complete"] = not any(uid < int(state["backfill_before"]) for uid in inventories[folder["name"]])
        has_more |= any(not state.get("history_complete", False)
                        or int(state.get("last_uid", 0)) < int(state.get("recent_through_uid", state.get("last_uid", 0)))
                        or not state.get("flags", {}).get("complete", False)
                        for state in states.values())
    now = now_timestamp()
    with connect(data_root) as db:
        db.execute("""INSERT INTO sync_state(connection_id, last_sync_at, last_error, cursor, last_incremental_sync_at)
        VALUES (?, ?, '', ?, ?) ON CONFLICT(connection_id) DO UPDATE SET last_sync_at=excluded.last_sync_at,
        last_error='', cursor=excluded.cursor, last_incremental_sync_at=excluded.last_incremental_sync_at""",
                   (connection_id, now, json.dumps({"version": 2, "folders": states, "next_folder_index": next_folder_index,
                    "next_flag_folder_index": next_flag_folder, "inventory_remaining": sorted(uninspected), "next_work": next_work}) if persist_cursor else json.dumps(cursor), now))
    return {"connection_id": connection_id, "synced_at": now, "synced_threads": synced,
            "synced_messages": synced, "checked_flag_messages": flags_checked,
            "work_units": initial_budget - budget.remaining, "has_more": has_more, "mode": "imap_smtp"}


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
