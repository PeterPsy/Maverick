"""Focused tests for the canonical OpenDesign adapter and export manifest."""

from __future__ import annotations

from base64 import b64decode
import importlib.util
from io import BytesIO
import json
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch
from zipfile import ZIP_DEFLATED, ZipFile


APP_ROOT = Path(__file__).resolve().parents[1]
BACKEND_ROOT = APP_ROOT / "backend"
sys.path.insert(0, str(BACKEND_ROOT))
SPEC = importlib.util.spec_from_file_location("design_studio_adapter_service", BACKEND_ROOT / "service.py")
assert SPEC is not None and SPEC.loader is not None
service = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(service)


class _CorrelationStore:
    def get(self, run_id: str) -> dict:
        return {
            "od_run_id": run_id,
            "od_project_id": "od_adapter_export",
            "status": "succeeded",
            "runtime_session_id": "runtime-session-1",
            "turn_id": "turn-1",
            "stream_id": "stream-1",
            "request_id": "request-1",
            "correlation_id": "request-1",
            "updated_at": "2026-08-05T12:00:00+00:00",
            "result_package": {
                "schema": "open-design.run-result-package.v1",
                "run": {"id": run_id, "projectId": "od_adapter_export", "status": "succeeded"},
            },
        }


class OpenDesignAdapterTests(unittest.TestCase):
    def test_export_is_run_scoped_reproducible_and_contains_real_artifact_digests(self) -> None:
        with TemporaryDirectory() as temp_dir:
            payload = {
                "app_id": "design-studio",
                "workspace_id": "default",
                "data_root": str(Path(temp_dir) / "data" / "design-studio"),
            }

            def request(_payload: dict, path: str) -> dict:
                if path == "/api/projects/od_adapter_export":
                    return {"project": {"id": "od_adapter_export", "name": "Export proof"}}
                if path == "/api/projects/od_adapter_export/files":
                    return {
                        "files": [
                            {
                                "name": "index.html",
                                "size": 17,
                                "mime": "text/html",
                                "localPath": "/private/opendesign/projects/od_adapter_export/index.html",
                            }
                        ]
                    }
                raise AssertionError(path)

            bundle = {
                "oci_reference": "ghcr.io/nexu-io/od:0.16.1",
                "oci_index_digest": "sha256:" + "a" * 64,
                "artifact_sha256": "b" * 64,
            }
            archive_buffer = BytesIO()
            with ZipFile(archive_buffer, "w", compression=ZIP_DEFLATED) as archive:
                archive.writestr("index.html", b"<h1>adapter</h1>\n")
            with (
                patch.object(service, "_opendesign_request", side_effect=request),
                patch.object(service, "_opendesign_bytes_post", return_value=archive_buffer.getvalue()),
                patch.object(service, "store_for_payload", return_value=_CorrelationStore()),
                patch.object(service, "_opendesign_bundle_summary", return_value=bundle),
                patch.object(
                    service,
                    "_opendesign_runtime_status",
                    return_value={
                        "runtime_artifact_sha256": "b" * 64,
                        "web_overlay_sha256": "c" * 64,
                    },
                ),
            ):
                result = service.export_to_storage(
                    payload,
                    {"project_id": "od_adapter_export", "run_id": "od_run_export_1"},
                )

            self.assertEqual(result["od_project_id"], "od_adapter_export")
            self.assertEqual(result["manifest"]["od_run_id"], "od_run_export_1")
            self.assertEqual(result["manifest"]["provenance"]["runtime_session_id"], "runtime-session-1")
            self.assertEqual(result["manifest"]["provenance"]["oci_reference"], bundle["oci_reference"])
            self.assertEqual(result["manifest"]["provenance"]["runtime_artifact_sha256"], "b" * 64)
            self.assertEqual(result["manifest"]["provenance"]["web_overlay_sha256"], "c" * 64)
            requests = result["dependency_backend_requests"]
            self.assertEqual(len(requests), 3)
            expected_root = "storage/generated/design-studio/od_adapter_export/od_run_export_1"
            self.assertEqual(
                [item["body"]["workspace_relative_path"] for item in requests],
                [
                    f"{expected_root}/project-files.zip",
                    f"{expected_root}/result-package.json",
                    f"{expected_root}/manifest.json",
                ],
            )
            self.assertTrue(all(item["body"]["mode"] == "create" for item in requests))
            self.assertTrue(all("confirm" not in item["body"] for item in requests))
            manifest_bytes = b64decode(requests[-1]["body"]["content_base64"])
            self.assertEqual(json.loads(manifest_bytes), result["manifest"])
            artifacts = result["manifest"]["artifacts"]
            self.assertEqual([item["media_type"] for item in artifacts], ["application/zip", "application/json"])
            self.assertTrue(all(len(item["sha256"]) == 64 for item in artifacts))
            exported_files = result["manifest"]["opendesign_files"]
            self.assertEqual(exported_files[0]["sha256"], service.sha256(b"<h1>adapter</h1>\n").hexdigest())
            self.assertNotIn("localPath", exported_files[0])
            self.assertNotIn("/private/", json.dumps(result["manifest"]))

    def test_archive_catalog_mismatch_is_rejected(self) -> None:
        archive_buffer = BytesIO()
        with ZipFile(archive_buffer, "w", compression=ZIP_DEFLATED) as archive:
            archive.writestr("unexpected.html", b"unexpected")
        with self.assertRaisesRegex(service.DesignStudioError, "does not match"):
            service._verified_archive_files(
                archive_buffer.getvalue(),
                [
                    {
                        "name": "index.html",
                        "path": "index.html",
                        "size_bytes": 17,
                        "media_type": "text/html",
                        "kind": "file",
                    }
                ],
            )


if __name__ == "__main__":
    unittest.main()
