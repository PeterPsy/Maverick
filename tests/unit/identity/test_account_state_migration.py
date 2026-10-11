"""App-owned personal caches survive workspace multi-account migration."""

import os
from pathlib import Path
import subprocess
import sys
import unittest

ROOT = Path(__file__).resolve().parents[3]


class AccountStateMigrationTests(unittest.TestCase):
    def run_app(self, app, script):
        # Domain modules intentionally have app-local names such as store;
        # exercise each migration in an isolated app process, as Core does.
        env = {**os.environ, "PYTHONPATH": str(ROOT / "apps" / app / "backend") + os.pathsep + str(ROOT)}
        result = subprocess.run([sys.executable, "-c", script], cwd=ROOT, env=env, capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_calendar_combines_account_events_and_preserves_later_edits(self):
        self.run_app("calendar", '''
import json, tempfile
from pathlib import Path
from platform_account import attach_platform_account
from store import read_state, update_state
with tempfile.TemporaryDirectory() as scratch:
    parent = Path(scratch)
    accounts = []
    originals = []
    for i in range(2):
        source = parent / f"google_{i}"
        source.mkdir()
        event = {"id": f"event_{i}", "title": f"Original {i}", "startTime": "2026-10-12T10:00:00Z", "endTime": "2026-10-12T11:00:00Z", "timezone": "UTC"}
        (source / "state.json").write_text(json.dumps({"events": [event]}))
        originals.append((source / "state.json").read_bytes())
        accounts.append({"account_id": source.name, "provider": "google", "email": f"{i}@example.com", "display_name": str(i), "services": ["calendar"], "access_handle": f"handle-{i}", "previous_data_root": str(source)})
    root = parent / "shared"
    payload = {"data_root": str(root), "external_accounts": accounts}
    attach_platform_account(payload)
    assert {e["id"] for e in read_state(root)["events"]} == {"event_0", "event_1"}
    def edit(state):
        state["events"][0]["title"] = "Later edit"
        return state
    update_state(root, edit)
    attach_platform_account({"data_root": str(root), "external_accounts": list(reversed(accounts))})
    assert read_state(root)["events"][0]["title"] == "Later edit"
    assert all((parent / f"google_{i}" / "state.json").read_bytes() == originals[i] for i in range(2))
    assert len(payload["app_secrets"]) == 2
''')

    def test_mail_preserves_drafts_search_index_and_never_imports_send_approval(self):
        self.run_app("mail", '''
import tempfile
from pathlib import Path
from platform_account import attach_platform_account
from database import connect, ensure_schema
with tempfile.TemporaryDirectory() as scratch:
    parent = Path(scratch)
    accounts = []
    for i in range(2):
        source = parent / f"google_{i}"
        ensure_schema(source)
        with connect(source) as db:
            db.execute("INSERT INTO drafts(id,connection_id,subject,body_text,status,created_at,updated_at) VALUES (?,?,?,?,?,?,?)", (f"draft-{i}", f"platform_google_{i}", f"Subject {i}", "Retained draft text", "draft", "2026-10-11", "2026-10-11"))
            db.execute("INSERT INTO send_confirmations(id,draft_id,token_hash,snapshot_hash,created_at,expires_at) VALUES (?,?,?,?,?,?)", (f"approval-{i}", f"draft-{i}", f"token-{i}", "snapshot", "2026-10-11", "2026-10-12"))
        accounts.append({"account_id": source.name, "provider": "google", "email": f"{i}@example.com", "display_name": str(i), "services": ["gmail"], "access_handle": f"handle-{i}", "previous_data_root": str(source)})
    root = parent / "shared"
    attach_platform_account({"data_root": str(root), "external_accounts": accounts})
    with connect(root) as db:
        assert db.execute("SELECT count(*) FROM drafts").fetchone()[0] == 2
        assert db.execute("SELECT count(*) FROM mail_fts WHERE mail_fts MATCH 'Retained'").fetchone()[0] == 2
        assert db.execute("SELECT count(*) FROM send_confirmations").fetchone()[0] == 0
        db.execute("UPDATE drafts SET body_text='Later edit' WHERE id='draft-0'")
    attach_platform_account({"data_root": str(root), "external_accounts": accounts})
    with connect(root) as db:
        assert db.execute("SELECT body_text FROM drafts WHERE id='draft-0'").fetchone()[0] == "Later edit"
    with connect(parent / "google_0") as db:
        assert db.execute("SELECT body_text FROM drafts WHERE id='draft-0'").fetchone()[0] == "Retained draft text"
''')

    def test_storage_preserves_json_and_sqlite_inventory_ids_and_metadata(self):
        self.run_app("storage", '''
import json, tempfile
from pathlib import Path
from core.app_sdk.storage import write_json_state
from platform_account import attach_platform_account
from inventory import load_inventory, uses_sqlite
from inventory_migration import initialize_inventory
from inventory_sqlite import InventoryIndex
with tempfile.TemporaryDirectory() as scratch:
    for indexed in (False, True):
        parent = Path(scratch) / str(indexed)
        parent.mkdir()
        accounts = []
        ids = []
        for i in range(2):
            source = parent / f"google_{i}"
            source.mkdir()
            file_id = "file_" + str(i + 1) * 32
            ids.append(file_id)
            record = {"file_id": file_id, "id": file_id, "provider": "google_drive", "connection_id": f"platform_google_{i}", "drive_file_id": "same-remote-id", "role": "drive", "relative_path": f"file-{i}.pdf", "name": f"file-{i}.pdf", "status": "active", "preview_kind": "pdf", "size_bytes": 7, "memory_node_id": f"memory-{i}", "remote_locator": {}, "capabilities": {"can_read": True}}
            if indexed:
                initialize_inventory(source)
                index = InventoryIndex(source)
                with index.transaction(write=True) as db:
                    index.put_file(db, record)
            else:
                write_json_state(source, "files.json", {"schema_version": "1", "files": [record], "directories": []})
            accounts.append({"account_id": source.name, "provider": "google", "email": f"{i}@example.com", "display_name": str(i), "services": ["drive"], "access_handle": f"handle-{i}", "previous_data_root": str(source)})
        root = parent / "shared"
        attach_platform_account({"data_root": str(root), "external_accounts": accounts})
        result = load_inventory(root)
        assert {r["file_id"] for r in result["files"]} == set(ids), result
        assert {r["memory_node_id"] for r in result["files"]} == {"memory-0", "memory-1"}
        assert uses_sqlite(root) == indexed
        attach_platform_account({"data_root": str(root), "external_accounts": list(reversed(accounts))})
        assert len(load_inventory(root)["files"]) == 2
''')
