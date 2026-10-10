"""Bounded account-wide Gmail history and expired-history recovery."""

import json
from urllib.parse import urlencode

from database import connect, now_timestamp
from provider_errors import ProviderError
from .cache_reconciliation import remove_thread


def refresh_history(provider, data_root, connection_id, access_token, max_threads):
    from .gmail import _cache_thread, _local_thread_id
    with connect(data_root) as db:
        row = db.execute("SELECT cursor, provider_history_id FROM sync_state WHERE connection_id=?", (connection_id,)).fetchone()
    try:
        cursor = json.loads(row["cursor"] or "{}") if row else {}
    except (ValueError, TypeError):
        cursor = {}
    if not isinstance(cursor, dict):
        cursor = {}
    history_id = str(row["provider_history_id"] or "") if row else ""
    if cursor.get("gmail_recovery"):
        return _recover(provider, data_root, connection_id, access_token, max_threads, cursor)
    if not history_id:
        baseline = str(provider.fetch_profile(access_token=access_token).get("historyId") or "")
        return {"synced_threads": 0, "has_more": False, "history_id": baseline, "cursor": cursor}
    progress = cursor.get("gmail_history") or {"start": history_id, "page": "", "pending": [], "target": history_id, "done": False}
    synced = 0
    # Bound both pages and fetched threads, even for label-only or empty events.
    pages = 0
    while synced < max_threads and pages < 4:
        if not progress["pending"] and not progress["done"]:
            params = {"startHistoryId": progress["start"], "maxResults": min(max_threads, 100)}
            if progress["page"]:
                params["pageToken"] = progress["page"]
            try:
                response = provider._gmail_json("GET", "history?" + urlencode(params), access_token=access_token)
            except ProviderError as error:
                if error.status != 404:
                    raise
                cursor.pop("gmail_history", None)
                cursor["gmail_recovery"] = {"page": "", "baseline": str(provider.fetch_profile(access_token=access_token).get("historyId") or "")}
                with connect(data_root) as db:
                    db.execute("DELETE FROM gmail_sync_inventory WHERE connection_id=?", (connection_id,))
                return _recover(provider, data_root, connection_id, access_token, max_threads, cursor)
            changed = set()
            for event in response.get("history", []):
                for name in ("messages", "messagesAdded", "messagesDeleted", "labelsAdded", "labelsRemoved"):
                    for item in event.get(name, []):
                        message = item.get("message", item)
                        if message.get("threadId"):
                            changed.add(str(message["threadId"]))
            progress["pending"] = sorted(changed)
            progress["page"] = str(response.get("nextPageToken") or "")
            progress["target"] = str(response.get("historyId") or progress["target"])
            progress["done"] = not progress["page"]
            pages += 1
        if not progress["pending"]:
            if progress["done"]:
                break
            continue
        thread_id = progress["pending"][0]
        try:
            thread = provider._fetch_thread(thread_id, access_token=access_token)
        except ProviderError as error:
            if error.status != 404:
                raise
            with connect(data_root) as db:
                remove_thread(db, _local_thread_id(connection_id, thread_id))
        else:
            _cache_thread(data_root, connection_id, thread)
        progress["pending"].pop(0)
        synced += 1
    more = bool(progress["pending"] or not progress["done"])
    if more:
        cursor["gmail_history"] = progress
    else:
        history_id = progress["target"]
        cursor.pop("gmail_history", None)
    return {"synced_threads": synced, "has_more": more, "history_id": history_id, "cursor": cursor}


def _recover(provider, data_root, connection_id, access_token, max_threads, cursor):
    from .gmail import _cache_thread
    progress = cursor["gmail_recovery"]
    params = {"maxResults": min(max_threads, 100), "includeSpamTrash": "true"}
    if progress["page"]:
        params["pageToken"] = progress["page"]
    response = provider._gmail_json("GET", "threads?" + urlencode(params), access_token=access_token)
    ids = [str(item["id"]) for item in response.get("threads", []) if item.get("id")]
    for thread_id in ids:
        try:
            thread = provider._fetch_thread(thread_id, access_token=access_token)
        except ProviderError as error:
            if error.status != 404:
                raise
        else:
            _cache_thread(data_root, connection_id, thread)
            with connect(data_root) as db:
                db.execute("INSERT OR IGNORE INTO gmail_sync_inventory(connection_id, provider_thread_id) VALUES (?, ?)", (connection_id, thread_id))
    progress["page"] = str(response.get("nextPageToken") or "")
    more = bool(progress["page"])
    if not more:
        with connect(data_root) as db:
            stale = db.execute("SELECT id FROM threads WHERE connection_id=? AND provider_thread_id NOT IN (SELECT provider_thread_id FROM gmail_sync_inventory WHERE connection_id=?)", (connection_id, connection_id)).fetchall()
            for row in stale:
                remove_thread(db, row[0])
            db.execute("DELETE FROM gmail_sync_inventory WHERE connection_id=?", (connection_id,))
        cursor.pop("gmail_recovery", None)
        # Query backfill tokens may have expired alongside provider history.
        cursor.pop("gmail", None)
    return {"synced_threads": len(ids), "has_more": more, "history_id": progress["baseline"], "cursor": cursor, "recovery": True}


def save_history(data_root, connection_id, result):
    with connect(data_root) as db:
        db.execute("""INSERT INTO sync_state(connection_id, cursor, provider_history_id, last_incremental_sync_at)
        VALUES (?, ?, ?, ?) ON CONFLICT(connection_id) DO UPDATE SET cursor=excluded.cursor,
        provider_history_id=excluded.provider_history_id, last_incremental_sync_at=excluded.last_incremental_sync_at""",
                   (connection_id, json.dumps(result["cursor"]), result["history_id"], now_timestamp()))
