"""Actual provider operations route distinct accounts without ID collisions."""

import unittest
from tests.unit.identity import test_account_state_migration as fixtures


class GoogleMultiAccountProviderTests(unittest.TestCase):
    run_app = fixtures.AccountStateMigrationTests.run_app

    def test_calendar_sync_uses_the_requested_account_and_namespaces_remote_events(self):
        self.run_app("calendar", '''
import tempfile
from pathlib import Path
from platform_account import attach_platform_account
from google_sync import sync_google_calendar
from store import read_state
calls = []
def transport(method, url, request):
    authorization = request["headers"]["authorization"]
    calls.append(authorization)
    if "/users/me/calendarList" in url:
        return 200, {"items": [{"id": "primary", "summary": "Primary", "timeZone": "UTC", "primary": True}]}
    if "/calendars/primary/events" in url:
        return 200, {"nextSyncToken": "sync", "items": [{"id": "same-event", "summary": authorization, "start": {"dateTime": "2026-10-12T10:00:00Z"}, "end": {"dateTime": "2026-10-12T11:00:00Z"}}]}
    raise AssertionError(url)
with tempfile.TemporaryDirectory() as scratch:
    root = Path(scratch)
    payload = {"data_root": str(root), "external_accounts": [{"account_id": f"google_{i}", "provider": "google", "email": f"{i}@example.com", "display_name": str(i), "picture_url": f"https://lh3.googleusercontent.com/a/{i}", "services": ["calendar"], "access_handle": f"handle-{i}"} for i in range(2)]}
    attach_platform_account(payload)
    assert {c["picture_url"] for c in read_state(root)["connections"]} == {f"https://lh3.googleusercontent.com/a/{i}" for i in range(2)}
    for i in range(2):
        sync_google_calendar(root, {"connection_id": f"platform_google_{i}"}, app_secrets=payload["app_secrets"], transport=transport)
    events = read_state(root)["events"]
    assert len(events) == 2, events
    assert {e["title"] for e in events} == {"Bearer handle-0", "Bearer handle-1"}
    assert len({e["id"] for e in events}) == 2
    assert calls == ["Bearer handle-0", "Bearer handle-0", "Bearer handle-1", "Bearer handle-1"], calls
''')

    def test_gmail_sync_uses_each_mailbox_handle_for_identical_provider_thread_ids(self):
        self.run_app("mail", '''
import tempfile
from pathlib import Path
from platform_account import attach_platform_account
from providers.gmail import GmailProvider
from database import connect
from store import list_connections
calls = []
def transport(request):
    authorization = request.get_header("Authorization")
    calls.append(authorization)
    url = request.full_url
    if url.endswith("/profile"):
        return {"historyId": "100"}
    if "/history?" in url:
        return {"historyId": "100", "history": []}
    if "/threads?" in url:
        return {"threads": [{"id": "same-thread"}]}
    if "/threads/same-thread?" in url:
        return {"id": "same-thread", "messages": [{"id": "same-message", "threadId": "same-thread", "labelIds": ["INBOX"], "internalDate": "1710000000000", "payload": {"mimeType": "text/plain", "headers": [{"name": "Subject", "value": authorization}], "body": {"data": "SGVsbG8="}}}]}
    raise AssertionError(url)
with tempfile.TemporaryDirectory() as scratch:
    root = Path(scratch)
    payload = {"data_root": str(root), "external_accounts": [{"account_id": f"google_{i}", "provider": "google", "email": f"{i}@example.com", "display_name": str(i), "picture_url": f"https://lh3.googleusercontent.com/a/{i}", "services": ["gmail"], "access_handle": f"handle-{i}"} for i in range(2)]}
    attach_platform_account(payload)
    assert {c["picture_url"] for c in list_connections(root)} == {f"https://lh3.googleusercontent.com/a/{i}" for i in range(2)}
    provider = GmailProvider(transport=transport)
    for i in range(2):
        provider.sync_incremental(root, f"platform_google_{i}", app_secrets=payload["app_secrets"])
    with connect(root) as db:
        rows = db.execute("SELECT id,connection_id,subject FROM threads").fetchall()
        assert len(rows) == 2, rows
        assert {r["subject"] for r in rows} == {"Bearer handle-0", "Bearer handle-1"}
        assert len({r["id"] for r in rows}) == 2
    for row in rows:
        provider.get_thread(root, row["id"], app_secrets=payload["app_secrets"])
    assert set(calls) == {"Bearer handle-0", "Bearer handle-1"}
''')

    def test_drive_lists_roots_with_each_account_handle_and_distinct_connection_ids(self):
        self.run_app("storage", '''
import tempfile
from pathlib import Path
from platform_account import attach_platform_account
from drive_connection_store import list_connections
from google_drive_provider import GoogleDriveProvider
calls = []
def transport(method, url, request):
    calls.append(request["headers"].get("authorization") or request["headers"].get("Authorization"))
    assert "/drive/v3/drives" in url, url
    return 200, {"drives": []}
with tempfile.TemporaryDirectory() as scratch:
    root = Path(scratch)
    payload = {"data_root": str(root), "external_accounts": [{"account_id": f"google_{i}", "provider": "google", "email": f"{i}@example.com", "display_name": str(i), "picture_url": f"https://lh3.googleusercontent.com/a/{i}", "services": ["drive"], "access_handle": f"handle-{i}"} for i in range(2)]}
    attach_platform_account(payload)
    assert {c["picture_url"] for c in list_connections(root)} == {f"https://lh3.googleusercontent.com/a/{i}" for i in range(2)}
    results = [GoogleDriveProvider(connection=item, app_secrets=payload["app_secrets"], transport=transport).list_roots() for item in list_connections(root)]
    assert calls == ["Bearer handle-0", "Bearer handle-1"], calls
    assert len(results) == 2
    assert {r["connection_id"] for r in results} == {"platform_google_0", "platform_google_1"}
    assert not ({f["id"] for f in results[0]["folders"]} & {f["id"] for f in results[1]["folders"]})
''')
