"""Saved workspace Drive references survive personal account adoption."""

from pathlib import Path
import tempfile
import unittest

from core.app_sdk.account_state import migrate_account_state

from tests.unit.identity import test_account_state_migration as fixtures


SETUP = '''
import tempfile
from pathlib import Path
from core.app_sdk.storage import write_json_state
from drive_connection_store import get_connection, read_state, replace_connection, resolve_connected_connection
from errors import StorageValidationError
from google_drive_provider import stable_storage_file_id
from inventory import load_inventory, upsert_remote_file_records, uses_sqlite
from inventory_migration import initialize_inventory
from platform_account import attach_platform_account
from service import handle_action, secret_lookup_for_drive_action

def account(number, **overrides):
    return {"account_id": f"google_{number}", "provider": "google", "email": f"owner{number}@example.com",
            "display_name": "Owner", "services": ["drive"], "access_handle": f"handle-{number}", **overrides}

def seed(source, indexed):
    if indexed:
        initialize_inventory(source)
    for number in range(3):
        connection_id = f"drive_old_{number}"
        replace_connection(source, {"id": connection_id, "status": "connected",
            "account_email": f"OWNER{number}@example.com", "credential": {"secret_ref": "workspace-credential"},
            "external_refs": {"google_subject": f"subject-{number}"}})
        upsert_remote_file_records(data_root=source, records=[{
            "file_id": stable_storage_file_id(connection_id, "video"), "provider": "google_drive",
            "connection_id": connection_id, "drive_file_id": "video", "remote_locator": {"drive_file_id": "video"},
            "name": f"video{number}.mp4", "content_type": "video/mp4", "preview_kind": "video",
            "status": "active", "role": "", "size_bytes": 5, "etag_or_version": "7", "memory_node_id": f"memory-{number}"}])

def invoke(source, root, accounts):
    payload = {"data_root": str(root), "workspace_data_root": str(source), "external_accounts": accounts}
    attach_platform_account(payload)
    return payload
'''


class WorkspaceDriveStateMigrationTests(unittest.TestCase):
    run_app = fixtures.AccountStateMigrationTests.run_app

    def test_imports_only_matching_accounts_once_and_preserves_inventory_and_later_edits(self):
        self.run_app("storage", SETUP + '''
with tempfile.TemporaryDirectory() as scratch:
    for indexed in (False, True):
        source = Path(scratch) / str(indexed)
        source.mkdir()
        seed(source, indexed)
        original_connections = (source / "drive_connections.json").read_bytes()
        original_inventory = load_inventory(source)
        root = source / "connected-accounts" / "owner" / "shared"
        # The earlier individual-account import has already run on deployed roots.
        write_json_state(root, ".platform-account-migrations.json", {"imported": ["google_0"]})
        invoke(source, root, [account(0)])
        old_id = stable_storage_file_id("drive_old_0", "video")
        files = load_inventory(root)["files"]
        assert [f["file_id"] for f in files] == [old_id], files
        assert files[0]["memory_node_id"] == "memory-0"
        assert uses_sqlite(root) == indexed
        assert get_connection(root, "drive_old_0")["id"] == "platform_google_0"
        assert len(read_state(root)["connections"]) == 1
        assert not get_connection(root, "drive_old_0")["credential"]["secret_ref"]
        try:
            get_connection(root, "drive_old_1")
        except ValueError:
            pass
        else:
            raise AssertionError("Unselected account was imported")
        # A new enabled account gets its own import even after the first migration.
        invoke(source, root, [account(1), account(0, default=True)])
        assert get_connection(root, "drive_old_1")["id"] == "platform_google_1"
        assert len(load_inventory(root)["files"]) == 2
        upsert_remote_file_records(data_root=root, records=[{**files[0], "name": "Later edit.mp4"}])
        invoke(source, root, [account(0), account(1, default=True)])
        edited = next(f for f in load_inventory(root)["files"] if f["file_id"] == old_id)
        assert edited["name"] == "Later edit.mp4"
        assert (source / "drive_connections.json").read_bytes() == original_connections
        assert load_inventory(source) == original_inventory
''')

    def test_saved_locator_and_stable_id_use_the_matching_account_for_provider_requests(self):
        self.run_app("storage", SETUP + '''
with tempfile.TemporaryDirectory() as scratch:
    source = Path(scratch)
    seed(source, True)
    root = source / "connected-accounts" / "owner" / "shared"
    payload = invoke(source, root, [account(1, default=True), account(0)])
    uploaded, generated = source / "uploaded", source / "generated"
    old_id = stable_storage_file_id("drive_old_0", "video")
    for locator in [{"connection_id": "drive_old_0", "drive_file_id": "video"},
                    {"stable_storage_file_id": old_id}]:
        lookup = secret_lookup_for_drive_action(root, uploaded, generated, {"action": "file.localize", **locator})
        assert lookup["resource_id"] == "platform_google_0", lookup
        calls = []
        def transport(method, url, request):
            calls.append(request["headers"]["Authorization"])
            return 200, {"id": "video", "name": "Current.mp4", "mimeType": "video/mp4",
                         "size": "5", "version": "7", "capabilities": {"canDownload": True}}
        status, result = handle_action(root, uploaded, generated,
            {"action": "file.reconcile", **locator, "_app_secrets": payload["app_secrets"]}, drive_transport=transport)
        assert status == 200, result
        assert result["connection_id"] == "platform_google_0", result
        assert calls and set(calls) == {"Bearer handle-0"}, calls
    # The originally saved stable ID still resolves after current metadata is refreshed.
    lookup = secret_lookup_for_drive_action(root, uploaded, generated,
        {"action": "file.localize_status", "stable_storage_file_id": old_id})
    assert lookup["resource_id"] == "platform_google_0", lookup
    status, media = handle_action(root, uploaded, generated,
        {"action": "file.media_stream", "stable_storage_file_id": old_id,
         "connection_id": "drive_old_0", "drive_file_id": "video", "source_version": "7",
         "_app_secrets": payload["app_secrets"]},
        drive_transport=transport, media_route=True, media_request_method="HEAD")
    assert status == 200, media
    assert media["stream_response"]["content_type"] == "video/mp4", media
    assert media["stream_response"]["content_length"] == 5, media
''')

    def test_revoked_account_keeps_saved_references_without_workspace_or_other_account_authority(self):
        self.run_app("storage", SETUP + '''
with tempfile.TemporaryDirectory() as scratch:
    source = Path(scratch)
    seed(source, False)
    root = source / "connected-accounts" / "owner" / "shared"
    invoke(source, root, [account(0), account(1)])
    # Even an old private manual connection cannot replace a withdrawn Core handle.
    replace_connection(root, {"id": "manual_private", "account_email": "owner0@example.com", "status": "connected"})
    for accounts in [[account(1)], [account(0, access_handle=""), account(1)], []]:
        payload = invoke(source, root, accounts)
        assert resolve_connected_connection(root, "drive_old_0")["status"] == "disconnected"
        calls = []
        def transport(*args):
            calls.append(args)
            raise AssertionError("Withdrawn authority reached Google")
        try:
            handle_action(root, source / "uploaded", source / "generated",
                {"action": "file.reconcile", "connection_id": "drive_old_0", "drive_file_id": "video",
                 "_app_secrets": payload.get("app_secrets", {})}, drive_transport=transport)
        except StorageValidationError:
            pass
        else:
            raise AssertionError("Withdrawn account accepted a provider operation")
        assert not calls
        assert len(load_inventory(root)["files"]) == 2
    invoke(source, root, [account(0)])
    assert resolve_connected_connection(root, "drive_old_0")["status"] == "connected"
''')

    def test_named_workspace_imports_are_independent_once_only_and_retry_after_failure(self):
        with tempfile.TemporaryDirectory() as scratch:
            source = Path(scratch)
            root = source / "connected-accounts" / "owner" / "shared"
            payload = {"data_root": str(root), "workspace_data_root": str(source), "external_accounts": []}
            calls = []

            def importer(source, root):
                calls.append((source, root))

            def failing(source, root):
                raise RuntimeError("incomplete import")

            migrate_account_state(payload, None, migrate_workspace=importer)
            with self.assertRaises(RuntimeError):
                migrate_account_state(payload, None, migrate_workspace=failing, workspace_migration_id="drive:first")
            for migration_id in ["drive:first", "drive:first", "drive:second", "drive:first"]:
                migrate_account_state(payload, None, migrate_workspace=importer, workspace_migration_id=migration_id)
            self.assertEqual(calls, [(source, root)] * 3)
