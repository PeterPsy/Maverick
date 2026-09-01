"""Stable Storage file-cache descriptor and version tests."""

from __future__ import annotations

from base64 import b64encode
import hashlib
import os
from pathlib import Path
import sys
import tempfile
import unittest
from urllib.parse import parse_qs, urlparse


APP_ROOT = Path(__file__).resolve().parents[1]
BACKEND_ROOT = APP_ROOT / "backend"
sys.path.insert(0, str(BACKEND_ROOT))

from drive_connection_store import replace_connection  # noqa: E402
from errors import StorageAuthorizationError  # noqa: E402
from file_cache_policy import stable_source_version  # noqa: E402
from google_drive_provider import stable_storage_file_id  # noqa: E402
from inventory import upsert_remote_file_records  # noqa: E402
from service import handle_action  # noqa: E402


class StorageFileCacheContractTest(unittest.TestCase):
    def test_local_files_publish_digest_versions_and_reject_stale_stream_urls(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            data_root = root / "data" / "storage"
            uploaded_root = root / "storage" / "uploaded"
            generated_root = root / "storage" / "generated"
            uploaded_root.mkdir(parents=True)
            generated_root.mkdir(parents=True)
            content = b"versioned local bytes"
            expected_sha256 = hashlib.sha256(content).hexdigest()

            _status, uploaded = handle_action(
                data_root,
                uploaded_root,
                generated_root,
                {
                    "action": "upload_file",
                    "role": "uploaded",
                    "file_name": "versioned.txt",
                    "content_base64": b64encode(content).decode("ascii"),
                },
            )
            file_record = uploaded["file"]

            self.assertEqual(file_record["source_version"], f"sha256:{expected_sha256}")
            descriptor_status, descriptor = handle_action(
                data_root,
                uploaded_root,
                generated_root,
                {
                    "action": "file.cache_descriptor",
                    "stable_storage_file_id": file_record["file_id"],
                    "source_version": file_record["source_version"],
                },
            )
            self.assertEqual(descriptor_status, 200)
            self.assertEqual(descriptor["schema"], "maverick.storage-file-cache-descriptor.v1")
            self.assertFalse(descriptor["eligible"])
            self.assertEqual(descriptor["reason_code"], "approval_required")
            self.assertEqual(descriptor["file"]["expected_sha256"], expected_sha256)
            self.assertEqual(descriptor["file"]["source_version"], file_record["source_version"])
            stream_query = parse_qs(urlparse(descriptor["file"]["media_url"]).query)
            self.assertEqual(stream_query["source_version"], [file_record["source_version"]])

            with self.assertRaisesRegex(Exception, "source_version is stale"):
                handle_action(
                    data_root,
                    uploaded_root,
                    generated_root,
                    {
                        "action": "file.media_stream",
                        "stable_storage_file_id": file_record["file_id"],
                        "source_version": "sha256:" + "0" * 64,
                    },
                    media_route=True,
                )

            local_path = uploaded_root / "versioned.txt"
            original_stat = local_path.stat()
            local_path.write_bytes(b"x" * len(content))
            os.utime(local_path, ns=(original_stat.st_atime_ns, original_stat.st_mtime_ns))
            with self.assertRaisesRegex(Exception, "source_version is stale"):
                handle_action(
                    data_root,
                    uploaded_root,
                    generated_root,
                    {
                        "action": "file.media_stream",
                        "stable_storage_file_id": file_record["file_id"],
                        "source_version": file_record["source_version"],
                        "_pwa_file_cache": "1",
                    },
                    media_route=True,
                )
            local_path.write_bytes(content)
            os.utime(local_path, ns=(original_stat.st_atime_ns, original_stat.st_mtime_ns))

            media_status, media = handle_action(
                data_root,
                uploaded_root,
                generated_root,
                {
                    "action": "file.media_stream",
                    "stable_storage_file_id": file_record["file_id"],
                    "source_version": file_record["source_version"],
                },
                media_route=True,
            )
            self.assertEqual(media_status, 200)
            self.assertEqual(media["file_response"]["etag"], expected_sha256)

    def test_admin_exact_version_approval_produces_and_revokes_an_eligible_descriptor(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            data_root = root / "data" / "storage"
            uploaded_root = root / "storage" / "uploaded"
            generated_root = root / "storage" / "generated"
            uploaded_root.mkdir(parents=True)
            generated_root.mkdir(parents=True)
            content = b"approved offline bytes"

            _status, uploaded = handle_action(
                data_root,
                uploaded_root,
                generated_root,
                {
                    "action": "upload_file",
                    "role": "uploaded",
                    "file_name": "approved.txt",
                    "content_base64": b64encode(content).decode("ascii"),
                },
            )
            file_record = uploaded["file"]
            approval_request = {
                "action": "file.cache_policy.approve",
                "stable_storage_file_id": file_record["file_id"],
                "source_version": file_record["source_version"],
                "confirm": True,
            }

            with self.assertRaises(StorageAuthorizationError):
                handle_action(data_root, uploaded_root, generated_root, approval_request)

            status, approved = handle_action(
                data_root,
                uploaded_root,
                generated_root,
                {
                    **approval_request,
                    "_workspace_role": "admin",
                    "_actor_user_id": "user-admin",
                },
            )

            self.assertEqual(status, 200)
            self.assertNotIn("approved_by_user_id", approved["approval"])
            self.assertEqual(approved["approval"]["source_version"], file_record["source_version"])
            self.assertTrue(approved["descriptor"]["eligible"])
            self.assertEqual(approved["descriptor"]["reason_code"], "approved_exact_version")
            self.assertEqual(approved["descriptor"]["policy"]["data_class"], "workspace_internal")
            self.assertTrue(approved["descriptor"]["policy"]["cache_approved"])

            descriptor_status, descriptor = handle_action(
                data_root,
                uploaded_root,
                generated_root,
                {
                    "action": "file.cache_descriptor",
                    "stable_storage_file_id": file_record["file_id"],
                    "source_version": file_record["source_version"],
                },
            )
            self.assertEqual(descriptor_status, 200)
            self.assertTrue(descriptor["eligible"])

            media_status, media = handle_action(
                data_root,
                uploaded_root,
                generated_root,
                {
                    "action": "file.media_stream",
                    "stable_storage_file_id": file_record["file_id"],
                    "source_version": file_record["source_version"],
                    "_pwa_file_cache": "1",
                },
                media_route=True,
                media_request_method="HEAD",
            )
            self.assertEqual(media_status, 200)
            self.assertEqual(media["file_response"]["etag"], hashlib.sha256(content).hexdigest())

            revoke_status, revoked = handle_action(
                data_root,
                uploaded_root,
                generated_root,
                {
                    "action": "file.cache_policy.revoke",
                    "stable_storage_file_id": file_record["file_id"],
                    "confirm": True,
                    "_workspace_role": "admin",
                },
            )
            self.assertEqual(revoke_status, 200)
            self.assertTrue(revoked["revoked"])
            _status, denied = handle_action(
                data_root,
                uploaded_root,
                generated_root,
                {
                    "action": "file.cache_descriptor",
                    "stable_storage_file_id": file_record["file_id"],
                    "source_version": file_record["source_version"],
                },
            )
            self.assertFalse(denied["eligible"])
            self.assertEqual(denied["reason_code"], "approval_required")

    def test_drive_files_publish_provider_versions_in_cache_descriptors(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            data_root = root / "data" / "storage"
            uploaded_root = root / "storage" / "uploaded"
            generated_root = root / "storage" / "generated"
            uploaded_root.mkdir(parents=True)
            generated_root.mkdir(parents=True)
            file_id = stable_storage_file_id("drive_conn_abc", "file-1")

            records = upsert_remote_file_records(
                data_root=data_root,
                records=[{
                    "id": file_id,
                    "file_id": file_id,
                    "provider": "google_drive",
                    "connection_id": "drive_conn_abc",
                    "drive_file_id": "file-1",
                    "remote_locator": {"drive_file_id": "file-1"},
                    "name": "Photo.jpg",
                    "extension": ".jpg",
                    "size_bytes": 123,
                    "modified_at": "2026-08-31T00:00:00Z",
                    "content_type": "image/jpeg",
                    "preview_kind": "image",
                    "etag_or_version": "revision-8",
                    "source_version": "revision-8",
                    "status": "active",
                }],
            )
            self.assertEqual(records[0]["source_version"], "revision-8")

            status, descriptor = handle_action(
                data_root,
                uploaded_root,
                generated_root,
                {
                    "action": "file.cache_descriptor",
                    "stable_storage_file_id": file_id,
                    "source_version": "revision-8",
                },
            )
            self.assertEqual(status, 200)
            self.assertEqual(descriptor["file"]["source_version"], "revision-8")
            self.assertEqual(descriptor["file"]["expected_sha256"], "")
            query = parse_qs(urlparse(descriptor["file"]["media_url"]).query)
            self.assertEqual(query["source_version"], ["revision-8"])
            self.assertIn("_app_secret_request", query)

    def test_drive_cache_version_does_not_fall_back_to_modified_metadata(self) -> None:
        self.assertEqual(
            stable_source_version({
                "provider": "google_drive",
                "etag_or_version": "2026-08-31T00:00:00Z",
                "modified_at": "2026-08-31T00:00:00Z",
                "source_version": "",
            }),
            "",
        )

    def test_drive_cache_stream_revalidates_provider_revision_before_serving(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            data_root = root / "data" / "storage"
            file_id = stable_storage_file_id("drive_conn_abc", "file-1")
            replace_connection(data_root, {
                "id": "drive_conn_abc",
                "provider": "google_drive",
                "status": "connected",
                "access_mode": "full_rw",
                "created_at": "2026-08-31T00:00:00+00:00",
            })
            upsert_remote_file_records(
                data_root=data_root,
                records=[{
                    "id": file_id,
                    "file_id": file_id,
                    "provider": "google_drive",
                    "connection_id": "drive_conn_abc",
                    "drive_file_id": "file-1",
                    "remote_locator": {"drive_file_id": "file-1"},
                    "name": "Photo.jpg",
                    "extension": ".jpg",
                    "size_bytes": 123,
                    "modified_at": "2026-08-31T00:00:00Z",
                    "content_type": "image/jpeg",
                    "preview_kind": "image",
                    "etag_or_version": "revision-8",
                    "source_version": "revision-8",
                    "status": "active",
                }],
            )

            with self.assertRaisesRegex(Exception, "source_version is stale"):
                handle_action(
                    data_root,
                    root / "storage" / "uploaded",
                    root / "storage" / "generated",
                    {
                        "action": "file.media_stream",
                        "stable_storage_file_id": file_id,
                        "source_version": "revision-8",
                        "_pwa_file_cache": "1",
                        "_app_secrets": {
                            "google-drive-oauth-client-id": "client-id",
                            "google-drive-oauth-client-secret": "client-secret",
                            "google-drive-refresh-token": "refresh-token",
                        },
                    },
                    drive_transport=_DriveRevisionTransport(),
                    media_route=True,
                    media_request_method="HEAD",
                    streaming_response_supported=True,
                )


class _DriveRevisionTransport:
    def __call__(self, method: str, url: str, request: dict[str, object]):
        if url == "https://oauth2.googleapis.com/token":
            return 200, {"access_token": "access-token"}
        if method == "GET" and urlparse(url).path == "/drive/v3/files/file-1":
            return 200, {
                "id": "file-1",
                "name": "Photo.jpg",
                "mimeType": "image/jpeg",
                "size": "123",
                "modifiedTime": "2026-08-31T00:01:00Z",
                "version": "revision-9",
                "capabilities": {"canDownload": True},
            }
        raise AssertionError(f"Unexpected Drive request: {method} {url}")


if __name__ == "__main__":
    unittest.main()
