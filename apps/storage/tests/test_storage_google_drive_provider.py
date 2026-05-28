"""Google Drive provider tests for Storage."""

from __future__ import annotations

import json
from pathlib import Path
import sys
import tempfile
import unittest
from urllib.parse import unquote
from urllib.parse import parse_qs, urlparse


APP_ROOT = Path(__file__).resolve().parents[1]
BACKEND_ROOT = APP_ROOT / "backend"
sys.path.insert(0, str(BACKEND_ROOT))

from drive_connection_store import replace_connection  # noqa: E402
from google_drive_provider import GoogleDriveProvider, stable_storage_file_id  # noqa: E402
from inventory import upsert_remote_file_records  # noqa: E402
from service import app_events_for_action, handle_action, secret_lookup_for_drive_action  # noqa: E402


SECRETS = {
    "google-drive-oauth-client-id": "client-id",
    "google-drive-oauth-client-secret": "client-secret",
    "google-drive-refresh-token": "refresh-token",
}

CONNECTION = {
    "id": "drive_conn_abc",
    "provider": "google_drive",
    "status": "connected",
    "access_mode": "full_rw",
}


class GoogleDriveProviderTest(unittest.TestCase):
    def test_drive_browse_actions_do_not_emit_catalog_invalidation_events(self) -> None:
        self.assertEqual(app_events_for_action("drive_list_roots"), [])
        self.assertEqual(app_events_for_action("drive_list_children"), [])
        self.assertEqual(app_events_for_action("drive_search"), [])
        self.assertEqual(app_events_for_action("drive_sync"), [
            {"type": "maverick.app.data-changed", "resource": "files"},
            {"type": "maverick.app.data-changed", "resource": "drive-connections"},
        ])

    def test_list_roots_normalizes_my_drive_shared_with_me_and_shared_drives(self) -> None:
        transport = FakeDriveTransport(
            {
                ("GET", "/drive/v3/drives"): {
                    "drives": [
                        {"id": "shared-drive-1", "name": "Client Shared"},
                    ]
                }
            }
        )
        provider = GoogleDriveProvider(connection=CONNECTION, app_secrets=SECRETS, transport=transport)

        result = provider.list_roots()

        self.assertEqual([item["name"] for item in result["folders"]], ["My Drive", "Shared with me", "Client Shared"])
        self.assertEqual({item["workspace_relative_path"] for item in result["folders"]}, {""})
        self.assertEqual({item["provider"] for item in result["folders"]}, {"google_drive"})
        self.assertEqual(result["folders"][2]["drive_file_id"], "shared-drive-1")
        self.assertEqual(result["folders"][2]["remote_locator"]["root_kind"], "shared_drive")
        self.assertTrue(result["folders"][0]["capabilities"]["can_read"])
        self.assertEqual(transport.token_refreshes, 1)

    def test_list_folder_children_derives_display_paths_and_drive_capabilities(self) -> None:
        transport = FakeDriveTransport(
            {
                ("GET", "/drive/v3/files/folder-1"): {
                    "id": "folder-1",
                    "name": "Acme",
                    "mimeType": "application/vnd.google-apps.folder",
                    "parents": ["root"],
                },
                ("GET", "/drive/v3/files"): {
                    "files": [
                        {
                            "id": "file-1",
                            "name": "Contract.pdf",
                            "mimeType": "application/pdf",
                            "parents": ["folder-1"],
                            "size": "1234",
                            "modifiedTime": "2026-05-28T10:00:00Z",
                            "version": "9",
                            "capabilities": {
                                "canDownload": True,
                                "canEdit": True,
                                "canMoveItemWithinDrive": True,
                                "canTrash": True,
                            },
                        },
                        {
                            "id": "folder-2",
                            "name": "Invoices",
                            "mimeType": "application/vnd.google-apps.folder",
                            "parents": ["folder-1"],
                            "capabilities": {"canDownload": True},
                        },
                    ]
                },
            }
        )
        provider = GoogleDriveProvider(connection=CONNECTION, app_secrets=SECRETS, transport=transport)

        result = provider.list_children(parent_drive_file_id="folder-1", limit=10)

        self.assertEqual(len(result["files"]), 1)
        file_record = result["files"][0]
        self.assertEqual(file_record["id"], stable_storage_file_id("drive_conn_abc", "file-1"))
        self.assertEqual(file_record["display_path"], "/My Drive/Acme/Contract.pdf")
        self.assertEqual(file_record["workspace_relative_path"], "")
        self.assertEqual(file_record["remote_locator"], {"drive_file_id": "file-1"})
        self.assertEqual(file_record["preview_kind"], "pdf")
        self.assertTrue(file_record["capabilities"]["can_write"])
        self.assertTrue(file_record["capabilities"]["can_move"])
        self.assertTrue(file_record["capabilities"]["can_delete"])
        self.assertEqual(result["folders"][0]["display_path"], "/My Drive/Acme/Invoices")
        list_call = transport.calls[-1]
        self.assertEqual(parse_qs(urlparse(list_call[1]).query)["pageSize"], ["11"])
        self.assertIn("'folder-1' in parents", parse_qs(urlparse(list_call[1]).query)["q"][0])

    def test_search_is_bounded_and_persists_remote_records_into_storage_catalog(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            data_root = root / "data" / "storage"
            replace_connection(data_root, {**CONNECTION, "created_at": "2026-05-28T00:00:00+00:00"})
            transport = FakeDriveTransport(
                {
                    ("GET", "/drive/v3/files"): {
                        "files": [
                            {
                                "id": "sheet-1",
                                "name": "Budget",
                                "mimeType": "application/vnd.google-apps.spreadsheet",
                                "modifiedTime": "2026-05-28T11:00:00Z",
                                "capabilities": {"canDownload": True, "canEdit": False},
                            }
                        ]
                    }
                }
            )

            status, result = handle_action(
                data_root,
                root / "storage" / "uploaded",
                root / "storage" / "generated",
                {
                    "action": "drive_search",
                    "connection_id": "drive_conn_abc",
                    "query": "budget",
                    "limit": 1,
                    "_app_secrets": SECRETS,
                },
                drive_transport=transport,
            )
            catalog_status, catalog = handle_action(
                data_root,
                root / "storage" / "uploaded",
                root / "storage" / "generated",
                {"action": "catalog", "file_ids": [stable_storage_file_id("drive_conn_abc", "sheet-1")]},
            )
            persisted = json.loads((data_root / "files.json").read_text(encoding="utf-8"))

        self.assertEqual(status, 200)
        self.assertEqual(result["files"][0]["provider"], "google_drive")
        self.assertEqual(result["files"][0]["preview_kind"], "spreadsheet")
        files_call = [call for call in transport.calls if "/drive/v3/files?" in call[1]][0]
        query_params = parse_qs(urlparse(files_call[1]).query)
        self.assertEqual(query_params["pageSize"], ["2"])
        self.assertIn("trashed = false", query_params["q"][0])
        self.assertEqual(catalog_status, 200)
        self.assertEqual(catalog["files"][0]["drive_file_id"], "sheet-1")
        self.assertEqual(catalog["files"][0]["workspace_relative_path"], "")
        self.assertNotIn("refresh-token", json.dumps(persisted, sort_keys=True))

    def test_metadata_marks_removed_and_inaccessible_without_local_paths(self) -> None:
        transport = FakeDriveTransport(
            {
                ("GET", "/drive/v3/files/missing-file"): (404, {"error": {"message": "File not found"}}),
                ("GET", "/drive/v3/files/blocked-file"): (403, {"error": {"message": "Forbidden"}}),
            }
        )
        provider = GoogleDriveProvider(connection=CONNECTION, app_secrets=SECRETS, transport=transport)

        missing = provider.metadata(drive_file_id="missing-file")
        blocked = provider.metadata(drive_file_id="blocked-file")

        self.assertEqual(missing["status"], "removed")
        self.assertEqual(blocked["status"], "inaccessible")
        self.assertEqual(missing["workspace_relative_path"], "")
        self.assertEqual(blocked["workspace_relative_path"], "")
        self.assertEqual(missing["stable_storage_file_id"], stable_storage_file_id("drive_conn_abc", "missing-file"))

    def test_drive_binary_preview_downloads_bounded_bytes_and_uses_temporary_cache(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            data_root = root / "data" / "storage"
            replace_connection(data_root, {**CONNECTION, "created_at": "2026-05-28T00:00:00+00:00"})
            transport = FakeDriveTransport(
                {
                    ("GET", "/drive/v3/files/bin-1"): [
                        {
                            "id": "bin-1",
                            "name": "Contract.pdf",
                            "mimeType": "application/pdf",
                            "size": "11",
                            "modifiedTime": "2026-05-28T11:00:00Z",
                            "version": "3",
                            "capabilities": {"canDownload": True},
                        },
                        b"hello bytes",
                        {
                            "id": "bin-1",
                            "name": "Contract.pdf",
                            "mimeType": "application/pdf",
                            "size": "11",
                            "modifiedTime": "2026-05-28T11:00:00Z",
                            "version": "3",
                            "capabilities": {"canDownload": True},
                        },
                    ]
                }
            )

            status, first = handle_action(
                data_root,
                root / "storage" / "uploaded",
                root / "storage" / "generated",
                {
                    "action": "drive_preview",
                    "connection_id": "drive_conn_abc",
                    "drive_file_id": "bin-1",
                    "max_bytes": 64,
                    "_app_secrets": SECRETS,
                },
                drive_transport=transport,
            )
            second_status, second = handle_action(
                data_root,
                root / "storage" / "uploaded",
                root / "storage" / "generated",
                {
                    "action": "drive_preview",
                    "connection_id": "drive_conn_abc",
                    "drive_file_id": "bin-1",
                    "max_bytes": 64,
                    "_app_secrets": SECRETS,
                },
                drive_transport=transport,
            )

        media_calls = [call for call in transport.calls if parse_qs(urlparse(call[1]).query).get("alt") == ["media"]]
        self.assertEqual(status, 200)
        self.assertEqual(first["content_base64"], "aGVsbG8gYnl0ZXM=")
        self.assertEqual(first["content_type"], "application/pdf")
        self.assertFalse(first["cache_hit"])
        self.assertEqual(second_status, 200)
        self.assertTrue(second["cache_hit"])
        self.assertEqual(len(media_calls), 1)
        self.assertEqual(first["file"]["workspace_relative_path"], "")

    def test_drive_google_doc_exports_readable_text_centrally(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            data_root = root / "data" / "storage"
            replace_connection(data_root, {**CONNECTION, "created_at": "2026-05-28T00:00:00+00:00"})
            transport = FakeDriveTransport(
                {
                    ("GET", "/drive/v3/files/doc-1"): {
                        "id": "doc-1",
                        "name": "Plan",
                        "mimeType": "application/vnd.google-apps.document",
                        "modifiedTime": "2026-05-28T11:00:00Z",
                        "version": "5",
                        "capabilities": {"canDownload": True},
                    },
                    ("GET", "/drive/v3/files/doc-1/export"): b"Readable plan text",
                }
            )

            status, result = handle_action(
                data_root,
                root / "storage" / "uploaded",
                root / "storage" / "generated",
                {
                    "action": "drive_export",
                    "connection_id": "drive_conn_abc",
                    "drive_file_id": "doc-1",
                    "export_mime_type": "readable_text",
                    "_app_secrets": SECRETS,
                },
                drive_transport=transport,
            )

        export_call = [call for call in transport.calls if call[1].startswith("https://www.googleapis.com/drive/v3/files/doc-1/export")][0]
        self.assertEqual(status, 200)
        self.assertEqual(result["content_type"], "text/plain")
        self.assertEqual(result["content_base64"], "UmVhZGFibGUgcGxhbiB0ZXh0")
        self.assertEqual(parse_qs(urlparse(export_call[1]).query)["mimeType"], ["text/plain"])

    def test_drive_read_clamps_google_native_export_limit_for_ui_downloads(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            data_root = root / "data" / "storage"
            replace_connection(data_root, {**CONNECTION, "created_at": "2026-05-28T00:00:00+00:00"})
            transport = FakeDriveTransport(
                {
                    ("GET", "/drive/v3/files/doc-1"): {
                        "id": "doc-1",
                        "name": "Small plan",
                        "mimeType": "application/vnd.google-apps.document",
                        "modifiedTime": "2026-05-28T11:00:00Z",
                        "version": "5",
                        "capabilities": {"canDownload": True},
                    },
                    ("GET", "/drive/v3/files/doc-1/export"): b"short text",
                }
            )

            status, result = handle_action(
                data_root,
                root / "storage" / "uploaded",
                root / "storage" / "generated",
                {
                    "action": "drive_read",
                    "connection_id": "drive_conn_abc",
                    "drive_file_id": "doc-1",
                    "max_bytes": 100 * 1024 * 1024,
                    "_app_secrets": SECRETS,
                },
                drive_transport=transport,
            )

        export_call = [call for call in transport.calls if call[1].startswith("https://www.googleapis.com/drive/v3/files/doc-1/export")][0]
        self.assertEqual(status, 200)
        self.assertEqual(result["content_type"], "text/plain")
        self.assertEqual(result["content_base64"], "c2hvcnQgdGV4dA==")
        self.assertEqual(transport.calls[-1][2]["max_bytes"], 10 * 1024 * 1024)
        self.assertEqual(parse_qs(urlparse(export_call[1]).query)["mimeType"], ["text/plain"])

    def test_drive_index_returns_memory_source_payload_without_local_path_identity(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            data_root = root / "data" / "storage"
            replace_connection(data_root, {**CONNECTION, "created_at": "2026-05-28T00:00:00+00:00"})
            transport = FakeDriveTransport(
                {
                    ("GET", "/drive/v3/files/doc-1"): {
                        "id": "doc-1",
                        "name": "Plan",
                        "mimeType": "application/vnd.google-apps.document",
                        "modifiedTime": "2026-05-28T11:00:00Z",
                        "version": "5",
                        "capabilities": {"canDownload": True},
                    },
                    ("GET", "/drive/v3/files/doc-1/export"): b"Readable plan text",
                }
            )

            status, result = handle_action(
                data_root,
                root / "storage" / "uploaded",
                root / "storage" / "generated",
                {
                    "action": "drive_index",
                    "connection_id": "drive_conn_abc",
                    "drive_file_id": "doc-1",
                    "_app_secrets": SECRETS,
                },
                drive_transport=transport,
            )
            catalog_status, catalog = handle_action(
                data_root,
                root / "storage" / "uploaded",
                root / "storage" / "generated",
                {"action": "catalog", "file_ids": [stable_storage_file_id("drive_conn_abc", "doc-1")]},
            )

        self.assertEqual(status, 200)
        self.assertEqual(result["status"], "ready_for_memory")
        self.assertEqual(result["preview_text"], "Readable plan text")
        self.assertEqual(result["source_version"], "5")
        self.assertEqual(result["memory_source"]["source_kind"], "remote_storage_file")
        self.assertEqual(result["memory_source"]["owning_app_id"], "storage")
        self.assertEqual(result["memory_source"]["entity_type"], "file")
        self.assertEqual(result["memory_source"]["entity_id"], stable_storage_file_id("drive_conn_abc", "doc-1"))
        self.assertEqual(result["memory_source"]["workspace_relative_path"], "")
        self.assertEqual(result["memory_source"]["metadata"]["drive_file_id"], "doc-1")
        self.assertEqual(catalog_status, 200)
        self.assertEqual(catalog["files"][0]["workspace_relative_path"], "")

    def test_drive_sheets_preview_uses_csv_and_explicit_export_uses_xlsx(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            data_root = root / "data" / "storage"
            replace_connection(data_root, {**CONNECTION, "created_at": "2026-05-28T00:00:00+00:00"})
            sheet_metadata = {
                "id": "sheet-1",
                "name": "Budget",
                "mimeType": "application/vnd.google-apps.spreadsheet",
                "modifiedTime": "2026-05-28T11:00:00Z",
                "version": "7",
                "capabilities": {"canDownload": True},
            }
            transport = FakeDriveTransport(
                {
                    ("GET", "/drive/v3/files/sheet-1"): [sheet_metadata, sheet_metadata, sheet_metadata],
                    ("GET", "/drive/v3/files/sheet-1/export"): [b"Name,Amount\nA,1\n", b"xlsx-bytes"],
                }
            )

            preview_status, preview = handle_action(
                data_root,
                root / "storage" / "uploaded",
                root / "storage" / "generated",
                {
                    "action": "drive_preview",
                    "connection_id": "drive_conn_abc",
                    "drive_file_id": "sheet-1",
                    "_app_secrets": SECRETS,
                },
                drive_transport=transport,
            )
            export_status, exported = handle_action(
                data_root,
                root / "storage" / "uploaded",
                root / "storage" / "generated",
                {
                    "action": "drive_export",
                    "connection_id": "drive_conn_abc",
                    "drive_file_id": "sheet-1",
                    "export_mime_type": "xlsx",
                    "_app_secrets": SECRETS,
                },
                drive_transport=transport,
            )

        export_mimes = [
            unquote(parse_qs(urlparse(call[1]).query)["mimeType"][0])
            for call in transport.calls
            if "/drive/v3/files/sheet-1/export" in call[1]
        ]
        self.assertEqual(preview_status, 200)
        self.assertEqual(preview["export_mime_type"], "text/csv")
        self.assertEqual(preview["preview_text"], "Name,Amount\nA,1\n")
        self.assertEqual(export_status, 200)
        self.assertEqual(exported["content_type"], "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
        self.assertEqual(export_mimes, ["text/csv", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"])

    def test_drive_google_export_rejects_requests_over_google_ten_mb_limit(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            data_root = root / "data" / "storage"
            replace_connection(data_root, {**CONNECTION, "created_at": "2026-05-28T00:00:00+00:00"})
            transport = FakeDriveTransport(
                {
                    ("GET", "/drive/v3/files/doc-1"): {
                        "id": "doc-1",
                        "name": "Plan",
                        "mimeType": "application/vnd.google-apps.document",
                        "capabilities": {"canDownload": True},
                    }
                }
            )

            with self.assertRaisesRegex(Exception, "10485760"):
                handle_action(
                    data_root,
                    root / "storage" / "uploaded",
                    root / "storage" / "generated",
                    {
                        "action": "drive_export",
                        "connection_id": "drive_conn_abc",
                        "drive_file_id": "doc-1",
                        "max_bytes": 10 * 1024 * 1024 + 1,
                        "_app_secrets": SECRETS,
                    },
                    drive_transport=transport,
                )

    def test_drive_read_reports_missing_permissions(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            data_root = root / "data" / "storage"
            replace_connection(data_root, {**CONNECTION, "created_at": "2026-05-28T00:00:00+00:00"})
            transport = FakeDriveTransport(
                {
                    ("GET", "/drive/v3/files/no-download"): {
                        "id": "no-download",
                        "name": "Blocked.pdf",
                        "mimeType": "application/pdf",
                        "size": "12",
                        "capabilities": {"canDownload": False},
                    }
                }
            )

            with self.assertRaisesRegex(Exception, "download/export permission"):
                handle_action(
                    data_root,
                    root / "storage" / "uploaded",
                    root / "storage" / "generated",
                    {
                        "action": "drive_read",
                        "connection_id": "drive_conn_abc",
                        "drive_file_id": "no-download",
                        "_app_secrets": SECRETS,
                    },
                    drive_transport=transport,
                )

    def test_drive_read_reports_file_not_accessible(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            data_root = root / "data" / "storage"
            replace_connection(data_root, {**CONNECTION, "created_at": "2026-05-28T00:00:00+00:00"})
            transport = FakeDriveTransport(
                {
                    ("GET", "/drive/v3/files/blocked-file"): (403, {"error": {"message": "Forbidden"}}),
                }
            )

            with self.assertRaisesRegex(Exception, "not accessible"):
                handle_action(
                    data_root,
                    root / "storage" / "uploaded",
                    root / "storage" / "generated",
                    {
                        "action": "drive_read",
                        "connection_id": "drive_conn_abc",
                        "drive_file_id": "blocked-file",
                        "_app_secrets": SECRETS,
                    },
                    drive_transport=transport,
                )

    def test_drive_write_without_capability_fails_closed_before_upload(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            data_root = root / "data" / "storage"
            replace_connection(data_root, {**CONNECTION, "created_at": "2026-05-28T00:00:00+00:00"})
            transport = FakeDriveTransport(
                {
                    ("GET", "/drive/v3/files/folder-1"): {
                        "id": "folder-1",
                        "name": "Locked",
                        "mimeType": "application/vnd.google-apps.folder",
                        "parents": ["root"],
                        "capabilities": {"canAddChildren": False},
                    }
                }
            )

            with self.assertRaisesRegex(Exception, "add files"):
                handle_action(
                    data_root,
                    root / "storage" / "uploaded",
                    root / "storage" / "generated",
                    {
                        "action": "drive_write",
                        "connection_id": "drive_conn_abc",
                        "parent_drive_file_id": "folder-1",
                        "file_name": "notes.txt",
                        "content": "hello",
                        "_app_secrets": SECRETS,
                    },
                    drive_transport=transport,
                )

        upload_calls = [call for call in transport.calls if "/upload/drive/v3/files" in call[1]]
        self.assertEqual(upload_calls, [])

    def test_drive_upload_and_content_update_are_capability_checked_and_persisted(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            data_root = root / "data" / "storage"
            replace_connection(data_root, {**CONNECTION, "created_at": "2026-05-28T00:00:00+00:00"})
            transport = FakeDriveTransport(
                {
                    ("GET", "/drive/v3/files/folder-1"): {
                        "id": "folder-1",
                        "name": "Docs",
                        "mimeType": "application/vnd.google-apps.folder",
                        "parents": ["root"],
                        "capabilities": {"canAddChildren": True},
                    },
                    ("POST", "/upload/drive/v3/files"): {
                        "id": "new-file",
                        "name": "notes.txt",
                        "mimeType": "text/plain",
                        "parents": ["folder-1"],
                        "size": "5",
                        "capabilities": {"canDownload": True, "canModifyContent": True},
                    },
                    ("GET", "/drive/v3/files/new-file"): {
                        "id": "new-file",
                        "name": "notes.txt",
                        "mimeType": "text/plain",
                        "parents": ["folder-1"],
                        "size": "5",
                        "capabilities": {"canDownload": True, "canModifyContent": True},
                    },
                    ("PATCH", "/upload/drive/v3/files/new-file"): {
                        "id": "new-file",
                        "name": "notes.txt",
                        "mimeType": "text/plain",
                        "parents": ["folder-1"],
                        "size": "7",
                        "version": "2",
                        "capabilities": {"canDownload": True, "canModifyContent": True},
                    },
                }
            )

            upload_status, upload = handle_action(
                data_root,
                root / "storage" / "uploaded",
                root / "storage" / "generated",
                {
                    "action": "drive_write",
                    "connection_id": "drive_conn_abc",
                    "parent_drive_file_id": "folder-1",
                    "file_name": "notes.txt",
                    "content": "hello",
                    "_app_secrets": SECRETS,
                },
                drive_transport=transport,
            )
            update_status, updated = handle_action(
                data_root,
                root / "storage" / "uploaded",
                root / "storage" / "generated",
                {
                    "action": "drive_write",
                    "connection_id": "drive_conn_abc",
                    "drive_file_id": "new-file",
                    "content_base64": "dXBkYXRlZA==",
                    "content_type": "text/plain",
                    "_app_secrets": SECRETS,
                },
                drive_transport=transport,
            )
            persisted = json.loads((data_root / "files.json").read_text(encoding="utf-8"))

        self.assertEqual(upload_status, 200)
        self.assertEqual(upload["status"], "uploaded")
        self.assertEqual(upload["file"]["workspace_relative_path"], "")
        self.assertEqual(update_status, 200)
        self.assertEqual(updated["status"], "updated")
        self.assertTrue(any(item["drive_file_id"] == "new-file" for item in persisted["files"]))
        self.assertNotIn("refresh-token", json.dumps(persisted, sort_keys=True))
        upload_request = [call for call in transport.calls if call[0] == "POST" and "/upload/drive/v3/files" in call[1]][0]
        self.assertIn(b"notes.txt", upload_request[2]["data"])

    def test_drive_rename_and_move_are_audited(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            data_root = root / "data" / "storage"
            replace_connection(data_root, {**CONNECTION, "created_at": "2026-05-28T00:00:00+00:00"})
            transport = FakeDriveTransport(
                {
                    ("GET", "/drive/v3/files/file-1"): [
                        {
                            "id": "file-1",
                            "name": "Old.txt",
                            "mimeType": "text/plain",
                            "parents": ["root"],
                            "capabilities": {"canRename": True, "canMoveItemWithinDrive": True, "canDownload": True},
                        },
                        {
                            "id": "file-1",
                            "name": "New.txt",
                            "mimeType": "text/plain",
                            "parents": ["root"],
                            "capabilities": {"canRename": True, "canMoveItemWithinDrive": True, "canDownload": True},
                        },
                    ],
                    ("PATCH", "/drive/v3/files/file-1"): [
                        {
                            "id": "file-1",
                            "name": "New.txt",
                            "mimeType": "text/plain",
                            "parents": ["root"],
                            "capabilities": {"canRename": True, "canMoveItemWithinDrive": True, "canDownload": True},
                        },
                        {
                            "id": "file-1",
                            "name": "New.txt",
                            "mimeType": "text/plain",
                            "parents": ["folder-2"],
                            "capabilities": {"canRename": True, "canMoveItemWithinDrive": True, "canDownload": True},
                        },
                    ],
                    ("GET", "/drive/v3/files/folder-2"): [
                        {
                            "id": "folder-2",
                            "name": "Target",
                            "mimeType": "application/vnd.google-apps.folder",
                            "parents": ["root"],
                            "capabilities": {"canAddChildren": True},
                        },
                        {
                            "id": "folder-2",
                            "name": "Target",
                            "mimeType": "application/vnd.google-apps.folder",
                            "parents": ["root"],
                            "capabilities": {"canAddChildren": True},
                        },
                    ],
                }
            )

            rename_status, renamed = handle_action(
                data_root,
                root / "storage" / "uploaded",
                root / "storage" / "generated",
                {
                    "action": "drive_rename",
                    "connection_id": "drive_conn_abc",
                    "drive_file_id": "file-1",
                    "new_name": "New.txt",
                    "_app_secrets": SECRETS,
                },
                drive_transport=transport,
            )
            move_status, moved = handle_action(
                data_root,
                root / "storage" / "uploaded",
                root / "storage" / "generated",
                {
                    "action": "drive_move",
                    "connection_id": "drive_conn_abc",
                    "drive_file_id": "file-1",
                    "target_parent_drive_file_id": "folder-2",
                    "_app_secrets": SECRETS,
                },
                drive_transport=transport,
            )
            state = json.loads((data_root / "drive_connections.json").read_text(encoding="utf-8"))

        self.assertEqual(rename_status, 200)
        self.assertEqual(renamed["file"]["name"], "New.txt")
        self.assertEqual(move_status, 200)
        self.assertEqual(moved["file"]["display_path"], "/My Drive/Target/New.txt")
        audit_actions = [item["action"] for item in state["audit_log"]]
        self.assertIn("drive.file.rename", audit_actions)
        self.assertIn("drive.file.move", audit_actions)

    def test_drive_trash_requires_confirmation_and_is_audited(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            data_root = root / "data" / "storage"
            replace_connection(data_root, {**CONNECTION, "created_at": "2026-05-28T00:00:00+00:00"})
            transport = FakeDriveTransport(
                {
                    ("GET", "/drive/v3/files/file-1"): {
                        "id": "file-1",
                        "name": "Delete.txt",
                        "mimeType": "text/plain",
                        "parents": ["root"],
                        "capabilities": {"canTrash": True, "canDownload": True},
                    },
                    ("PATCH", "/drive/v3/files/file-1"): {
                        "id": "file-1",
                        "name": "Delete.txt",
                        "mimeType": "text/plain",
                        "parents": ["root"],
                        "trashed": True,
                        "capabilities": {"canTrash": True, "canDownload": True},
                    },
                }
            )

            with self.assertRaisesRegex(Exception, "requires confirm"):
                handle_action(
                    data_root,
                    root / "storage" / "uploaded",
                    root / "storage" / "generated",
                    {
                        "action": "drive_trash",
                        "connection_id": "drive_conn_abc",
                        "drive_file_id": "file-1",
                        "_app_secrets": SECRETS,
                    },
                    drive_transport=transport,
                )
            status, result = handle_action(
                data_root,
                root / "storage" / "uploaded",
                root / "storage" / "generated",
                {
                    "action": "drive_trash",
                    "connection_id": "drive_conn_abc",
                    "drive_file_id": "file-1",
                    "confirm": True,
                    "_app_secrets": SECRETS,
                },
                drive_transport=transport,
            )
            state = json.loads((data_root / "drive_connections.json").read_text(encoding="utf-8"))

        self.assertEqual(status, 200)
        self.assertEqual(result["status"], "trashed")
        self.assertEqual(result["file"]["status"], "removed")
        self.assertEqual(len([call for call in transport.calls if call[0] == "PATCH"]), 1)
        self.assertIn("drive.file.trash", [item["action"] for item in state["audit_log"]])

    def test_missing_drive_secret_grant_fails_without_sensitive_values(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            data_root = root / "data" / "storage"
            replace_connection(data_root, {**CONNECTION, "created_at": "2026-05-28T00:00:00+00:00"})
            transport = FakeDriveTransport({})

            try:
                handle_action(
                    data_root,
                    root / "storage" / "uploaded",
                    root / "storage" / "generated",
                    {
                        "action": "drive_rename",
                        "connection_id": "drive_conn_abc",
                        "drive_file_id": "file-1",
                        "new_name": "Name.txt",
                        "_app_secrets": {},
                    },
                    drive_transport=transport,
                )
            except Exception as error:
                message = str(error)
            else:
                self.fail("Expected missing secret grant to fail closed.")

        self.assertIn("secret grant", message)
        self.assertNotIn("refresh-token", message)
        self.assertNotIn("client-secret", message)
        self.assertEqual(len(transport.calls), 0)

    def test_secret_lookup_resolves_stable_storage_file_id_to_drive_connection(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            data_root = root / "data" / "storage"
            file_id = stable_storage_file_id("drive_conn_abc", "file-1")
            replace_connection(data_root, {**CONNECTION, "created_at": "2026-05-28T00:00:00+00:00"})
            transport = FakeDriveTransport(
                {
                    ("GET", "/drive/v3/files"): {
                        "files": [
                            {
                                "id": "file-1",
                                "name": "Plan.txt",
                                "mimeType": "text/plain",
                                "capabilities": {"canDownload": True, "canModifyContent": True},
                            }
                        ]
                    }
                }
            )
            handle_action(
                data_root,
                root / "storage" / "uploaded",
                root / "storage" / "generated",
                {
                    "action": "drive_search",
                    "connection_id": "drive_conn_abc",
                    "query": "Plan",
                    "_app_secrets": SECRETS,
                },
                drive_transport=transport,
            )

            result = secret_lookup_for_drive_action(
                data_root,
                root / "storage" / "uploaded",
                root / "storage" / "generated",
                {"action": "drive_rename", "stable_storage_file_id": file_id, "new_name": "Plan 2.txt"},
            )

        self.assertEqual(
            result,
            {"requires_secrets": True, "resource_type": "drive_connection", "resource_id": "drive_conn_abc"},
        )

    def test_drive_sync_initializes_start_page_token_without_full_scan(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            data_root = root / "data" / "storage"
            replace_connection(data_root, {**CONNECTION, "created_at": "2026-05-28T00:00:00+00:00"})
            transport = FakeDriveTransport(
                {
                    ("GET", "/drive/v3/changes/startPageToken"): {"startPageToken": "token-1"},
                }
            )

            status, result = handle_action(
                data_root,
                root / "storage" / "uploaded",
                root / "storage" / "generated",
                {
                    "action": "drive_sync",
                    "connection_id": "drive_conn_abc",
                    "_app_secrets": SECRETS,
                },
                drive_transport=transport,
            )
            state = json.loads((data_root / "drive_connections.json").read_text(encoding="utf-8"))

        drive_paths = [urlparse(call[1]).path for call in transport.calls]
        self.assertEqual(status, 200)
        self.assertEqual(result["sync_mode"], "start_page_token")
        self.assertEqual(result["changes_processed"], 0)
        self.assertEqual(result["sync_state"]["start_page_token"], "token-1")
        self.assertEqual(state["connections"][0]["sync_state"]["last_processed_page_token"], "token-1")
        self.assertNotIn("/drive/v3/files", drive_paths)

    def test_drive_sync_applies_incremental_rename_move_delete_and_marks_memory_stale(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            data_root = root / "data" / "storage"
            file_1 = stable_storage_file_id("drive_conn_abc", "file-1")
            file_2 = stable_storage_file_id("drive_conn_abc", "file-2")
            replace_connection(
                data_root,
                {
                    **CONNECTION,
                    "created_at": "2026-05-28T00:00:00+00:00",
                    "sync_state": {
                        "start_page_token": "token-1",
                        "last_processed_page_token": "token-1",
                        "status": "healthy",
                    },
                },
            )
            upsert_remote_file_records(
                data_root=data_root,
                records=[
                    {
                        "id": file_1,
                        "provider": "google_drive",
                        "connection_id": "drive_conn_abc",
                        "drive_file_id": "file-1",
                        "name": "Old.txt",
                        "display_path": "/My Drive/Old.txt",
                        "content_type": "text/plain",
                        "etag_or_version": "1",
                    }
                ],
            )
            persisted = json.loads((data_root / "files.json").read_text(encoding="utf-8"))
            persisted["files"][0]["indexed"] = True
            persisted["files"][0]["index_status"] = "indexed"
            persisted["files"][0]["stale"] = False
            (data_root / "files.json").write_text(json.dumps(persisted), encoding="utf-8")
            transport = FakeDriveTransport(
                {
                    ("GET", "/drive/v3/changes"): {
                        "newStartPageToken": "token-2",
                        "changes": [
                            {
                                "fileId": "file-1",
                                "file": {
                                    "id": "file-1",
                                    "name": "New.txt",
                                    "mimeType": "text/plain",
                                    "parents": ["folder-2"],
                                    "modifiedTime": "2026-05-28T12:00:00Z",
                                    "version": "2",
                                    "capabilities": {"canDownload": True, "canRename": True},
                                },
                            },
                            {"fileId": "file-2", "removed": True},
                        ],
                    },
                    ("GET", "/drive/v3/files/folder-2"): {
                        "id": "folder-2",
                        "name": "Target",
                        "parents": ["root"],
                    },
                }
            )

            status, result = handle_action(
                data_root,
                root / "storage" / "uploaded",
                root / "storage" / "generated",
                {
                    "action": "drive_sync",
                    "connection_id": "drive_conn_abc",
                    "_app_secrets": SECRETS,
                },
                drive_transport=transport,
            )
            state = json.loads((data_root / "drive_connections.json").read_text(encoding="utf-8"))
            files = json.loads((data_root / "files.json").read_text(encoding="utf-8"))["files"]

        by_id = {item["file_id"]: item for item in files}
        drive_paths = [urlparse(call[1]).path for call in transport.calls]
        self.assertEqual(status, 200)
        self.assertEqual(result["changes_processed"], 2)
        self.assertEqual(result["synced_files"], 1)
        self.assertEqual(result["removed_file_count"], 1)
        self.assertEqual(result["removed_files"][0]["drive_file_id"], "file-2")
        self.assertEqual(state["connections"][0]["sync_state"]["last_processed_page_token"], "token-2")
        self.assertEqual(by_id[file_1]["name"], "New.txt")
        self.assertEqual(by_id[file_1]["display_path"], "/My Drive/Target/New.txt")
        self.assertTrue(by_id[file_1]["stale"])
        self.assertEqual(by_id[file_2]["status"], "removed")
        self.assertIn(file_1, result["stale_storage_file_ids"])
        self.assertIn({"owning_app_id": "storage", "entity_type": "file", "entity_id": file_1, "reason": "google_drive_change"}, result["memory_staleness"])
        self.assertNotIn("/drive/v3/files", drive_paths)

    def test_drive_sync_persists_next_page_cursor_when_change_page_limit_is_reached(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            data_root = root / "data" / "storage"
            replace_connection(
                data_root,
                {
                    **CONNECTION,
                    "created_at": "2026-05-28T00:00:00+00:00",
                    "sync_state": {
                        "start_page_token": "token-1",
                        "last_processed_page_token": "token-1",
                        "status": "healthy",
                    },
                },
            )
            transport = FakeDriveTransport(
                {
                    ("GET", "/drive/v3/changes"): {
                        "nextPageToken": "token-page-2",
                        "changes": [
                            {
                                "fileId": "file-1",
                                "file": {
                                    "id": "file-1",
                                    "name": "Plan.txt",
                                    "mimeType": "text/plain",
                                    "parents": ["root"],
                                    "version": "1",
                                    "capabilities": {"canDownload": True},
                                },
                            }
                        ],
                    },
                }
            )

            status, result = handle_action(
                data_root,
                root / "storage" / "uploaded",
                root / "storage" / "generated",
                {
                    "action": "drive_sync",
                    "connection_id": "drive_conn_abc",
                    "limit": 1,
                    "_app_secrets": SECRETS,
                },
                drive_transport=transport,
            )
            state = json.loads((data_root / "drive_connections.json").read_text(encoding="utf-8"))

        changes_call = [call for call in transport.calls if urlparse(call[1]).path == "/drive/v3/changes"][0]
        self.assertEqual(status, 200)
        self.assertTrue(result["has_more"])
        self.assertEqual(result["last_processed_page_token"], "token-page-2")
        self.assertEqual(state["connections"][0]["sync_state"]["last_processed_page_token"], "token-page-2")
        self.assertEqual(parse_qs(urlparse(changes_call[1]).query)["pageToken"], ["token-1"])
        self.assertEqual(parse_qs(urlparse(changes_call[1]).query)["pageSize"], ["1"])

    def test_drive_sync_redacts_provider_errors_in_state_and_exception(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            data_root = root / "data" / "storage"
            replace_connection(
                data_root,
                {
                    **CONNECTION,
                    "created_at": "2026-05-28T00:00:00+00:00",
                    "sync_state": {
                        "start_page_token": "token-1",
                        "last_processed_page_token": "token-1",
                        "status": "healthy",
                    },
                },
            )
            transport = FakeDriveTransport(
                {
                    ("GET", "/drive/v3/changes"): (
                        403,
                        {"error": {"message": "refresh-token client-secret authorization leaked"}},
                    ),
                }
            )

            try:
                handle_action(
                    data_root,
                    root / "storage" / "uploaded",
                    root / "storage" / "generated",
                    {
                        "action": "drive_sync",
                        "connection_id": "drive_conn_abc",
                        "_app_secrets": SECRETS,
                    },
                    drive_transport=transport,
                )
            except Exception as error:
                message = str(error)
            else:
                self.fail("Expected provider failure to raise a redacted Storage error.")
            state = json.loads((data_root / "drive_connections.json").read_text(encoding="utf-8"))

        serialized = json.dumps(state, sort_keys=True)
        self.assertIn("provider status 403", message)
        self.assertIn("provider status 403", serialized)
        self.assertNotIn("refresh-token", message)
        self.assertNotIn("client-secret", serialized)
        self.assertNotIn("authorization leaked", serialized)


class FakeDriveTransport:
    def __init__(self, responses: dict[tuple[str, str], object]) -> None:
        self.responses = responses
        self.calls: list[tuple[str, str, dict[str, object]]] = []
        self.token_refreshes = 0

    def __call__(self, method: str, url: str, request: dict[str, object]) -> tuple[int, dict[str, object]]:
        self.calls.append((method, url, request))
        if url == "https://oauth2.googleapis.com/token":
            data = request["data"]
            assert isinstance(data, dict)
            self.token_refreshes += 1
            self.assert_secret_request(data)
            return 200, {"access_token": "access-token"}
        parsed = urlparse(url)
        key = (method, parsed.path)
        if key not in self.responses:
            raise AssertionError(f"Unexpected Drive request: {method} {url}")
        response = self.responses[key]
        if isinstance(response, list):
            if not response:
                raise AssertionError(f"No remaining fake response for: {method} {url}")
            response = response.pop(0)
        if isinstance(response, tuple):
            return response
        if isinstance(response, bytes):
            max_bytes = int(request.get("max_bytes") or 0)
            if max_bytes and len(response) > max_bytes:
                return 200, response[: max_bytes + 1]
            return 200, response
        return 200, response if isinstance(response, dict) else {}

    @staticmethod
    def assert_secret_request(data: dict[str, object]) -> None:
        assert data["client_id"] == "client-id"
        assert data["client_secret"] == "client-secret"
        assert data["refresh_token"] == "refresh-token"
        assert data["grant_type"] == "refresh_token"


if __name__ == "__main__":
    unittest.main()
