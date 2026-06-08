"""Google Drive provider tests for Storage."""

from __future__ import annotations

import io
import json
import hashlib
from pathlib import Path
import sys
import tempfile
import unittest
import zipfile
from urllib.parse import unquote
from urllib.parse import parse_qs, urlparse


APP_ROOT = Path(__file__).resolve().parents[1]
BACKEND_ROOT = APP_ROOT / "backend"
BACKEND_MODULE_NAMES = {path.stem for path in BACKEND_ROOT.glob("*.py")}


def evict_foreign_backend_modules() -> None:
    backend_root = BACKEND_ROOT.resolve()
    for name, module in list(sys.modules.items()):
        if name not in BACKEND_MODULE_NAMES:
            continue
        module_file = getattr(module, "__file__", None)
        if not module_file:
            continue
        try:
            resolved = Path(module_file).resolve()
        except OSError:
            continue
        if resolved != backend_root / resolved.name:
            sys.modules.pop(name, None)


evict_foreign_backend_modules()
sys.path.insert(0, str(BACKEND_ROOT))

from drive_connection_store import replace_connection  # noqa: E402
import drive_localization  # noqa: E402
from google_drive_provider import GoogleDriveProvider, stable_storage_file_id  # noqa: E402
from inventory import load_inventory, upsert_remote_file_records  # noqa: E402
import service as storage_service  # noqa: E402
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


def docx_bytes(text: str) -> bytes:
    payload = io.BytesIO()
    with zipfile.ZipFile(payload, "w") as archive:
        archive.writestr(
            "word/document.xml",
            f"<w:document xmlns:w='http://schemas.openxmlformats.org/wordprocessingml/2006/main'><w:body><w:p><w:r><w:t>{text}</w:t></w:r></w:p></w:body></w:document>",
        )
    return payload.getvalue()


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
        self.assertFalse(result["pagination"]["has_more"])
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
        list_query = parse_qs(urlparse(list_call[1]).query)
        self.assertEqual(list_query["pageSize"], ["10"])
        self.assertEqual(list_query["corpora"], ["user"])
        self.assertIn("'folder-1' in parents", list_query["q"][0])
        self.assertFalse(result["pagination"]["has_more"])

    def test_list_folder_children_uses_drive_page_tokens(self) -> None:
        transport = FakeDriveTransport(
            {
                ("GET", "/drive/v3/files/folder-1"): {
                    "id": "folder-1",
                    "name": "Acme",
                    "mimeType": "application/vnd.google-apps.folder",
                    "parents": ["root"],
                },
                ("GET", "/drive/v3/files"): {
                    "nextPageToken": "token-2",
                    "files": [
                        {
                            "id": "file-1",
                            "name": "Contract.pdf",
                            "mimeType": "application/pdf",
                            "parents": ["folder-1"],
                            "size": "1234",
                            "modifiedTime": "2026-05-28T10:00:00Z",
                            "version": "9",
                            "capabilities": {"canDownload": True},
                        },
                    ],
                },
            }
        )
        provider = GoogleDriveProvider(connection=CONNECTION, app_secrets=SECRETS, transport=transport)

        result = provider.list_children(parent_drive_file_id="folder-1", limit=1, page_token="token-1")

        list_call = transport.calls[-1]
        query = parse_qs(urlparse(list_call[1]).query)
        self.assertEqual(query["pageSize"], ["1"])
        self.assertEqual(query["pageToken"], ["token-1"])
        self.assertTrue(result["pagination"]["has_more"])
        self.assertEqual(result["pagination"]["next_page_token"], "token-2")
        self.assertEqual(result["files"][0]["name"], "Contract.pdf")

    def test_drive_access_token_cache_is_reused_across_provider_instances(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            cache_root = Path(temp_dir) / "drive_temp_cache"
            transport = FakeDriveTransport({("GET", "/drive/v3/drives"): {"drives": []}})
            first = GoogleDriveProvider(connection=CONNECTION, app_secrets=SECRETS, transport=transport, cache_root=cache_root)
            second = GoogleDriveProvider(connection=CONNECTION, app_secrets=SECRETS, transport=transport, cache_root=cache_root)

            first.list_roots()
            second.list_roots()

        self.assertEqual(transport.token_refreshes, 1)

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
        self.assertEqual(query_params["pageSize"], ["1"])
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

    def test_drive_preview_reuses_persisted_metadata_when_stable_id_is_available(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            data_root = root / "data" / "storage"
            file_id = stable_storage_file_id("drive_conn_abc", "bin-1")
            replace_connection(data_root, {**CONNECTION, "created_at": "2026-05-28T00:00:00+00:00"})
            upsert_remote_file_records(
                data_root=data_root,
                records=[
                    {
                        "id": file_id,
                        "file_id": file_id,
                        "provider": "google_drive",
                        "connection_id": "drive_conn_abc",
                        "drive_file_id": "bin-1",
                        "remote_locator": {"drive_file_id": "bin-1"},
                        "status": "active",
                        "role": "",
                        "relative_path": "",
                        "workspace_relative_path": "",
                        "display_path": "/My Drive/Contract.pdf",
                        "name": "Contract.pdf",
                        "extension": ".pdf",
                        "size_bytes": 11,
                        "modified_at": "2026-05-28T11:00:00Z",
                        "content_type": "application/pdf",
                        "preview_kind": "pdf",
                        "sha256": "",
                        "etag_or_version": "3",
                        "capabilities": {
                            "can_read": True,
                            "can_write": False,
                            "can_move": False,
                            "can_rename": False,
                            "can_delete": False,
                            "can_preview": True,
                            "can_index": True,
                        },
                    }
                ],
            )
            transport = FakeDriveTransport({("GET", "/drive/v3/files/bin-1"): b"hello bytes"})

            status, result = handle_action(
                data_root,
                root / "storage" / "uploaded",
                root / "storage" / "generated",
                {
                    "action": "drive_preview",
                    "connection_id": "drive_conn_abc",
                    "drive_file_id": "bin-1",
                    "stable_storage_file_id": file_id,
                    "max_bytes": 64,
                    "_app_secrets": SECRETS,
                },
                drive_transport=transport,
            )

        metadata_calls = [
            call for call in transport.calls
            if urlparse(call[1]).path == "/drive/v3/files/bin-1" and parse_qs(urlparse(call[1]).query).get("alt") != ["media"]
        ]
        self.assertEqual(status, 200)
        self.assertEqual(result["content_base64"], "aGVsbG8gYnl0ZXM=")
        self.assertEqual(metadata_calls, [])

    def test_drive_localize_caches_binary_and_media_stream_uses_local_file_response(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            data_root = root / "data" / "storage"
            file_id = stable_storage_file_id("drive_conn_abc", "video-1")
            content = b"0123456789"
            replace_connection(data_root, {**CONNECTION, "created_at": "2026-05-28T00:00:00+00:00"})
            transport = FakeDriveTransport(
                {
                    ("GET", "/drive/v3/files/video-1"): [
                        {
                            "id": "video-1",
                            "name": "Clip.mp4",
                            "mimeType": "video/mp4",
                            "size": str(len(content)),
                            "modifiedTime": "2026-05-28T11:00:00Z",
                            "version": "8",
                            "capabilities": {"canDownload": True},
                        },
                        content,
                    ]
                }
            )

            status, localized = handle_action(
                data_root,
                root / "storage" / "uploaded",
                root / "storage" / "generated",
                {
                    "action": "file.localize",
                    "connection_id": "drive_conn_abc",
                    "drive_file_id": "video-1",
                    "_app_secrets": SECRETS,
                },
                drive_transport=transport,
            )
            second_status, second = handle_action(
                data_root,
                root / "storage" / "uploaded",
                root / "storage" / "generated",
                {
                    "action": "file.localize",
                    "stable_storage_file_id": file_id,
                    "_app_secrets": SECRETS,
                },
                drive_transport=transport,
            )
            media_status, media = handle_action(
                data_root,
                root / "storage" / "uploaded",
                root / "storage" / "generated",
                {"action": "file.media_stream", "stable_storage_file_id": file_id, "download": True, "_media_route": True},
            )
            media_calls = [call for call in transport.calls if parse_qs(urlparse(call[1]).query).get("alt") == ["media"]]
            local_path = Path(media["file_response"]["path"])
            local_path_bytes = local_path.read_bytes()
            local_path_is_under_cache = local_path.is_relative_to(data_root / "drive_local_cache")
            stream_query = parse_qs(urlparse(localized["stream_url"]).query)
        self.assertEqual(status, 200)
        self.assertEqual(localized["status"], "ready")
        self.assertEqual(localized["stable_storage_file_id"], file_id)
        self.assertEqual(localized["localization"]["sha256"], hashlib.sha256(content).hexdigest())
        self.assertNotIn("local_path", localized)
        self.assertEqual(local_path_bytes, content)
        self.assertTrue(local_path_is_under_cache)
        self.assertEqual(stream_query["stable_storage_file_id"], [file_id])
        self.assertIn("/api/apps/storage/media?", localized["stream_url"])
        self.assertIn("download=1", localized["download_url"])
        self.assertEqual(second_status, 200)
        self.assertTrue(second["localization"]["cache_hit"])
        self.assertEqual(media_status, 200)
        self.assertEqual(media["file_response"]["content_type"], "video/mp4")
        self.assertTrue(media["file_response"]["download"])
        self.assertEqual(stream_query["localization_id"], [localized["localization"]["id"]])
        self.assertEqual(stream_query["source_version"], ["8"])
        self.assertIn("_app_secret_request", stream_query)
        self.assertEqual(len(media_calls), 1)

    def test_drive_media_stream_proxies_requested_range_when_full_cache_is_missing(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            data_root = root / "data" / "storage"
            file_id = stable_storage_file_id("drive_conn_abc", "video-1")
            content = b"0123456789"
            replace_connection(data_root, {**CONNECTION, "created_at": "2026-05-28T00:00:00+00:00"})
            upsert_remote_file_records(
                data_root=data_root,
                records=[
                    {
                        "id": file_id,
                        "file_id": file_id,
                        "stable_storage_file_id": file_id,
                        "provider": "google_drive",
                        "connection_id": "drive_conn_abc",
                        "drive_file_id": "video-1",
                        "remote_locator": {"drive_file_id": "video-1"},
                        "role": "",
                        "relative_path": "",
                        "workspace_relative_path": "",
                        "name": "Clip.mp4",
                        "extension": ".mp4",
                        "size_bytes": len(content),
                        "modified_at": "2026-05-28T11:00:00Z",
                        "content_type": "video/mp4",
                        "preview_kind": "video",
                        "sha256": "",
                        "etag_or_version": "8",
                        "capabilities": {"can_read": True, "can_preview": True},
                        "status": "active",
                    }
                ],
            )
            transport = FakeDriveTransport({("GET", "/drive/v3/files/video-1"): content})

            status, media = handle_action(
                data_root,
                root / "storage" / "uploaded",
                root / "storage" / "generated",
                {
                    "action": "file.media_stream",
                    "_media_route": True,
                    "stable_storage_file_id": file_id,
                    "source_version": "8",
                    "_app_secrets": SECRETS,
                    "_request_headers": {"range": "bytes=2-5"},
                },
                drive_transport=transport,
            )
            range_path = Path(media["file_response"]["path"])
            full_cache_path = data_root / "drive_local_cache" / media["localization"]["id"][:2] / media["localization"]["id"] / "content.bin"
            range_bytes = range_path.read_bytes()
            full_cache_exists = full_cache_path.exists()
            media_calls = [call for call in transport.calls if parse_qs(urlparse(call[1]).query).get("alt") == ["media"]]

        self.assertEqual(status, 200)
        self.assertEqual(range_bytes, b"2345")
        self.assertEqual(media["file_response"]["served_range"], {"start": 2, "end": 5, "size": len(content)})
        self.assertEqual(media["file_response"]["content_type"], "video/mp4")
        self.assertFalse(full_cache_exists)
        self.assertEqual(len(media_calls), 1)

    def test_drive_media_stream_rejects_stale_source_version(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            data_root = root / "data" / "storage"
            file_id = stable_storage_file_id("drive_conn_abc", "video-1")
            upsert_remote_file_records(
                data_root=data_root,
                records=[
                    {
                        "id": file_id,
                        "file_id": file_id,
                        "stable_storage_file_id": file_id,
                        "provider": "google_drive",
                        "connection_id": "drive_conn_abc",
                        "drive_file_id": "video-1",
                        "remote_locator": {"drive_file_id": "video-1"},
                        "role": "",
                        "relative_path": "",
                        "workspace_relative_path": "",
                        "name": "Clip.mp4",
                        "extension": ".mp4",
                        "size_bytes": 10,
                        "modified_at": "2026-05-28T11:00:00Z",
                        "content_type": "video/mp4",
                        "preview_kind": "video",
                        "sha256": "",
                        "etag_or_version": "8",
                        "capabilities": {"can_read": True, "can_preview": True},
                        "status": "active",
                    }
                ],
            )

            with self.assertRaisesRegex(Exception, "source_version is stale"):
                handle_action(
                    data_root,
                    root / "storage" / "uploaded",
                    root / "storage" / "generated",
                    {"action": "file.media_stream", "_media_route": True, "stable_storage_file_id": file_id, "source_version": "7"},
                )

    def test_media_stream_action_requires_internal_media_route_marker(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            data_root = root / "data" / "storage"
            uploaded_root = root / "storage" / "uploaded"
            uploaded_root.mkdir(parents=True)
            _status, uploaded = handle_action(
                data_root,
                uploaded_root,
                root / "storage" / "generated",
                {
                    "action": "upload_file",
                    "role": "uploaded",
                    "file_name": "clip.mp4",
                    "content_base64": "Y2xpcA==",
                },
            )

            with self.assertRaisesRegex(Exception, "authenticated Storage media route"):
                handle_action(
                    data_root,
                    uploaded_root,
                    root / "storage" / "generated",
                    {"action": "file.media_stream", "stable_storage_file_id": uploaded["file"]["id"]},
                )

    def test_drive_local_cache_cleanup_prunes_stale_sources_and_lru_over_budget(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            data_root = Path(temp_dir) / "data" / "storage"
            stale_dir = data_root / "drive_local_cache" / "aa" / "aa-old"
            keep_dir = data_root / "drive_local_cache" / "bb" / "bb-new"
            stale_dir.mkdir(parents=True)
            keep_dir.mkdir(parents=True)
            (stale_dir / "content.bin").write_bytes(b"stale-source")
            (keep_dir / "content.bin").write_bytes(b"keep-source")
            (stale_dir / "metadata.json").write_text(
                json.dumps(
                    {
                        "id": "aa-old",
                        "status": "ready",
                        "stable_storage_file_id": "file_drive_1",
                        "source_version": "1",
                        "content_type": "video/mp4",
                        "size_bytes": len(b"stale-source"),
                        "updated_at": "2026-05-01T00:00:00+00:00",
                    }
                ),
                encoding="utf-8",
            )
            (keep_dir / "metadata.json").write_text(
                json.dumps(
                    {
                        "id": "bb-new",
                        "status": "ready",
                        "stable_storage_file_id": "file_drive_2",
                        "source_version": "1",
                        "content_type": "video/mp4",
                        "size_bytes": len(b"keep-source"),
                        "updated_at": "2026-05-02T00:00:00+00:00",
                    }
                ),
                encoding="utf-8",
            )
            original_budget = drive_localization.DRIVE_LOCAL_CACHE_MAX_BYTES
            try:
                drive_localization.DRIVE_LOCAL_CACHE_MAX_BYTES = len(b"keep-source") + 1
                drive_localization.cleanup_drive_local_cache(
                    data_root=data_root,
                    current_file_record={"id": "file_drive_1", "file_id": "file_drive_1", "source_version": "2"},
                    keep_localization_id="bb-new",
                )
            finally:
                drive_localization.DRIVE_LOCAL_CACHE_MAX_BYTES = original_budget
            stale_dir_exists = stale_dir.exists()
            keep_dir_exists = keep_dir.exists()

        self.assertFalse(stale_dir_exists)
        self.assertTrue(keep_dir_exists)

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
            inventory_file = {item["file_id"]: item for item in load_inventory(data_root)["files"]}[
                stable_storage_file_id("drive_conn_abc", "doc-1")
            ]
            ack_status, ack = handle_action(
                data_root,
                root / "storage" / "uploaded",
                root / "storage" / "generated",
                {
                    "action": "drive_mark_indexed",
                    "stable_storage_file_id": stable_storage_file_id("drive_conn_abc", "doc-1"),
                    "source_version": result["source_version"],
                },
            )
            ack_inventory_file = {item["file_id"]: item for item in load_inventory(data_root)["files"]}[
                stable_storage_file_id("drive_conn_abc", "doc-1")
            ]

        self.assertEqual(status, 200)
        self.assertEqual(result["status"], "ready_for_memory")
        self.assertEqual(result["preview_text"], "Readable plan text")
        self.assertEqual(result["source_version"], "5")
        self.assertFalse(result["preview_truncated"])
        self.assertEqual(result["memory_source"]["source_kind"], "remote_storage_file")
        self.assertEqual(result["memory_source"]["owning_app_id"], "storage")
        self.assertEqual(result["memory_source"]["entity_type"], "file")
        self.assertEqual(result["memory_source"]["entity_id"], stable_storage_file_id("drive_conn_abc", "doc-1"))
        self.assertEqual(result["memory_source"]["file_id"], stable_storage_file_id("drive_conn_abc", "doc-1"))
        self.assertEqual(result["memory_source"]["provider"], "google_drive")
        self.assertEqual(result["memory_source"]["title"], "Plan")
        self.assertEqual(result["memory_source"]["workspace_relative_path"], "")
        self.assertEqual(result["memory_source"]["metadata"]["stable_storage_file_id"], stable_storage_file_id("drive_conn_abc", "doc-1"))
        self.assertEqual(result["memory_source"]["metadata"]["source_version"], "5")
        self.assertEqual(result["memory_source"]["metadata"]["drive_file_id"], "doc-1")
        self.assertEqual(catalog_status, 200)
        self.assertEqual(catalog["files"][0]["workspace_relative_path"], "")
        self.assertFalse(inventory_file["indexed"])
        self.assertFalse(inventory_file["stale"])
        self.assertEqual(inventory_file["index_status"], "ready_for_memory")
        self.assertEqual(ack_status, 200)
        self.assertEqual(ack["status"], "indexed")
        self.assertTrue(ack_inventory_file["indexed"])
        self.assertFalse(ack_inventory_file["stale"])
        self.assertEqual(ack_inventory_file["index_status"], "indexed")

    def test_drive_index_bounds_preview_text_for_memory_ingest(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            data_root = root / "data" / "storage"
            replace_connection(data_root, {**CONNECTION, "created_at": "2026-05-28T00:00:00+00:00"})
            transport = FakeDriveTransport(
                {
                    ("GET", "/drive/v3/files/doc-1"): {
                        "id": "doc-1",
                        "name": "Long Plan",
                        "mimeType": "application/vnd.google-apps.document",
                        "modifiedTime": "2026-05-28T11:00:00Z",
                        "version": "5",
                        "capabilities": {"canDownload": True},
                    },
                    ("GET", "/drive/v3/files/doc-1/export"): ("A" * 20001).encode("utf-8"),
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

        self.assertEqual(status, 200)
        self.assertEqual(len(result["preview_text"]), 20000)
        self.assertTrue(result["preview_truncated"])
        self.assertTrue(result["truncated"])

    def test_drive_index_rejects_files_without_text_preview(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            data_root = root / "data" / "storage"
            replace_connection(data_root, {**CONNECTION, "created_at": "2026-05-28T00:00:00+00:00"})
            transport = FakeDriveTransport(
                {
                    ("GET", "/drive/v3/files/bin-1"): [
                        {
                            "id": "bin-1",
                            "name": "Scan.pdf",
                            "mimeType": "application/pdf",
                            "size": "9",
                            "modifiedTime": "2026-05-28T11:00:00Z",
                            "version": "3",
                            "capabilities": {"canDownload": True},
                        },
                        b"%PDF scan",
                    ],
                }
            )

            with self.assertRaisesRegex(Exception, "did not produce preview_text"):
                handle_action(
                    data_root,
                    root / "storage" / "uploaded",
                    root / "storage" / "generated",
                    {
                        "action": "drive_index",
                        "connection_id": "drive_conn_abc",
                        "drive_file_id": "bin-1",
                        "_app_secrets": SECRETS,
                    },
                    drive_transport=transport,
                )

    def test_drive_index_extracts_office_binary_preview_text(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            data_root = root / "data" / "storage"
            replace_connection(data_root, {**CONNECTION, "created_at": "2026-05-28T00:00:00+00:00"})
            transport = FakeDriveTransport(
                {
                    ("GET", "/drive/v3/files/docx-1"): [
                        {
                            "id": "docx-1",
                            "name": "Brief.docx",
                            "mimeType": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                            "size": "512",
                            "modifiedTime": "2026-05-28T11:00:00Z",
                            "version": "7",
                            "capabilities": {"canDownload": True},
                        },
                        docx_bytes("Drive DOCX says the renewal owner is Dana."),
                    ],
                }
            )

            status, result = handle_action(
                data_root,
                root / "storage" / "uploaded",
                root / "storage" / "generated",
                {
                    "action": "drive_index",
                    "connection_id": "drive_conn_abc",
                    "drive_file_id": "docx-1",
                    "_app_secrets": SECRETS,
                },
                drive_transport=transport,
            )

        self.assertEqual(status, 200)
        self.assertIn("renewal owner is Dana", result["preview_text"])
        self.assertEqual(result["source_version"], "7")
        self.assertEqual(result["memory_source"]["metadata"]["source_version"], "7")

    def test_drive_index_requires_source_version(self) -> None:
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
                    },
                    ("GET", "/drive/v3/files/doc-1/export"): b"Readable plan text",
                }
            )

            with self.assertRaisesRegex(Exception, "source_version"):
                handle_action(
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

    def test_drive_index_marks_file_for_later_sync_staleness(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            data_root = root / "data" / "storage"
            replace_connection(data_root, {**CONNECTION, "created_at": "2026-05-28T00:00:00+00:00"})
            index_transport = FakeDriveTransport(
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
                drive_transport=index_transport,
            )
            file_id = stable_storage_file_id("drive_conn_abc", "doc-1")
            ack_status, _ack = handle_action(
                data_root,
                root / "storage" / "uploaded",
                root / "storage" / "generated",
                {
                    "action": "drive_mark_indexed",
                    "stable_storage_file_id": file_id,
                    "source_version": result["source_version"],
                },
            )
            connection_state = json.loads((data_root / "drive_connections.json").read_text(encoding="utf-8"))
            connection_state["connections"][0]["sync_state"] = {
                "start_page_token": "token-1",
                "last_processed_page_token": "token-1",
                "status": "healthy",
            }
            (data_root / "drive_connections.json").write_text(json.dumps(connection_state), encoding="utf-8")
            sync_transport = FakeDriveTransport(
                {
                    ("GET", "/drive/v3/changes"): {
                        "newStartPageToken": "token-2",
                        "changes": [
                            {
                                "fileId": "doc-1",
                                "file": {
                                    "id": "doc-1",
                                    "name": "Plan",
                                    "mimeType": "application/vnd.google-apps.document",
                                    "modifiedTime": "2026-05-28T12:00:00Z",
                                    "version": "6",
                                    "capabilities": {"canDownload": True},
                                },
                            }
                        ],
                    }
                }
            )
            sync_status, sync = handle_action(
                data_root,
                root / "storage" / "uploaded",
                root / "storage" / "generated",
                {
                    "action": "drive_sync",
                    "connection_id": "drive_conn_abc",
                    "_app_secrets": SECRETS,
                },
                drive_transport=sync_transport,
            )
            inventory_file = {item["file_id"]: item for item in load_inventory(data_root)["files"]}[file_id]

        self.assertEqual(status, 200)
        self.assertEqual(ack_status, 200)
        self.assertEqual(sync_status, 200)
        self.assertTrue(inventory_file["indexed"])
        self.assertTrue(inventory_file["stale"])
        self.assertEqual(inventory_file["index_status"], "stale")
        self.assertIn(file_id, sync["stale_storage_file_ids"])
        self.assertEqual(sync["memory_staleness"][0]["entity_id"], file_id)
        self.assertEqual(sync["memory_staleness"][0]["connection_id"], "drive_conn_abc")
        self.assertEqual(sync["memory_staleness"][0]["drive_file_id"], "doc-1")
        self.assertEqual(sync["memory_staleness"][0]["indexed_source_version"], "5")
        self.assertEqual(sync["memory_staleness"][0]["source_version"], "6")

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

    def test_drive_write_rejects_content_above_write_budget_before_upload(self) -> None:
        original_limit = storage_service.MAX_WRITE_BYTES
        storage_service.MAX_WRITE_BYTES = 4
        transport = FakeDriveTransport({})
        try:
            with tempfile.TemporaryDirectory() as temp_dir:
                root = Path(temp_dir)
                data_root = root / "data" / "storage"

                with self.assertRaisesRegex(Exception, "at most 4 bytes"):
                    handle_action(
                        data_root,
                        root / "storage" / "uploaded",
                        root / "storage" / "generated",
                        {
                            "action": "drive_write",
                            "connection_id": "drive_conn_abc",
                            "parent_drive_file_id": "folder-1",
                            "file_name": "notes.txt",
                            "content_base64": "aGVsbG8=",
                            "_app_secrets": SECRETS,
                        },
                        drive_transport=transport,
                    )
        finally:
            storage_service.MAX_WRITE_BYTES = original_limit

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
        self.assertEqual(result["memory_staleness"][0]["entity_id"], file_1)
        self.assertEqual(result["memory_staleness"][0]["connection_id"], "drive_conn_abc")
        self.assertEqual(result["memory_staleness"][0]["drive_file_id"], "file-1")
        self.assertEqual(result["memory_staleness"][0]["source_version"], "2")
        self.assertIn(file_2, result["stale_storage_file_ids"])
        self.assertNotIn(file_2, [item["entity_id"] for item in result["memory_staleness"]])
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
