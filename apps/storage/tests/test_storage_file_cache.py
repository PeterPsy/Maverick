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

from google_drive_provider import stable_storage_file_id  # noqa: E402
from file_cache_policy import stable_source_version  # noqa: E402
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
            self.assertEqual(descriptor["reason_code"], "unclassified")
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


if __name__ == "__main__":
    unittest.main()
