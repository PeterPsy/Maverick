from __future__ import annotations

import json
import base64
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import time
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from companion_store import database
from companion_validation import instagram_url
from errors import BrowserValidationError
from service import handle_action, mcp_result_for_tool


class BrowserCompanionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.folder = TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.root = Path(self.folder.name)
        self.authority = {"workspace_id": "default", "user_id": "alice", "surface": "backend"}

    def call(self, action, **body):
        return handle_action(self.root, {"action": action, **body}, **self.authority)

    def sharing(self):
        status, result = self.call("companion.connect")
        self.assertEqual(status, 201)
        credentials = {"session_id": result["connection"]["session_id"], "connector_secret": result["connector_secret"]}
        status, _ = self.call("companion.poll", **credentials, url="https://www.instagram.com/martagiunti/", title="Marta")
        self.assertEqual(status, 200)
        return credentials

    def media_completion(self):
        credentials = self.sharing()
        _, queued = self.call("video.analyze", session_id=credentials["session_id"], frame_count=1)
        _, poll = self.call("companion.poll", **credentials, url="https://www.instagram.com/reel/example/")
        claim = {**credentials, "operation_id": queued["operation_id"], "lease_id": poll["command"]["lease_id"]}
        observation = {"source_url": "https://www.instagram.com/reel/example/", "frames": [{"base64": base64.b64encode(b"\xff\xd8\xffsample").decode()}],
                       "audio": {"base64": base64.b64encode(b"\x1aE\xdf\xa3sample").decode(), "duration_seconds": 2}}
        dependencies = {"dependencies": [{"alias": alias, "status": "resolved", "selected_provider_app_ids": [provider]} for alias, provider in [("storage-file-content-write", "storage"), ("speech-to-text", "speech")]]}
        status, result = handle_action(self.root, {"action": "companion.complete", **claim, "result": observation}, dependencies=dependencies, **self.authority)
        self.assertEqual((status, result["status"]), (200, "processing_media"))
        return queued["operation_id"], result["dependency_backend_requests"]

    def test_media_handoff_is_local_and_results_require_verified_callbacks(self):
        operation_id, requests = self.media_completion()
        self.assertEqual(len(requests), 3)
        for request in requests:
            body = {"action": "media.completed", "operation_id": operation_id, "request_id": request["request_id"],
                    "dependency_alias": request["dependency_alias"], "request": request, "dependency_backend_status": "completed"}
            if request["dependency_alias"] == "speech-to-text":
                self.assertIs(request["body"]["local_only"], True)
                body["dependency_backend_result"] = {"json": {"engine": "faster-whisper", "text": "Marta scia", "segments": []}}
            else:
                body["dependency_backend_result"] = {"json": {"file": {"file_id": request["request_id"], "workspace_relative_path": request["body"]["workspace_relative_path"]}}}
            self.assertEqual(handle_action(self.root, body, **self.authority)[0], 403)
            status, result = handle_action(self.root, body, workspace_id="default", surface="dependency_backend_request_callback")
            self.assertEqual(status, 200)
        _, result = self.call("operation.get", operation_id=operation_id)
        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["result"]["transcription"]["text"], "Marta scia")
        self.assertNotIn("base64", result["result"]["frames"][0])
        self.assertTrue(result["result"]["audio"]["storage"]["workspace_relative_path"].startswith("storage/generated/browser/"))

    def test_media_callback_cannot_publish_remote_transcript_or_overwrite_cancelled_work(self):
        operation_id, requests = self.media_completion()
        speech = next(r for r in requests if r["dependency_alias"] == "speech-to-text")
        body = {"action": "media.completed", "operation_id": operation_id, "request_id": speech["request_id"],
                "dependency_alias": "speech-to-text", "request": speech, "dependency_backend_status": "completed",
                "dependency_backend_result": {"json": {"engine": "deepgram", "text": "Untrusted remote transcription"}}}
        self.assertEqual(handle_action(self.root, body, workspace_id="other", surface="dependency_backend_request_callback")[0], 404)
        self.assertEqual(handle_action(self.root, body, workspace_id="default", surface="dependency_backend_request_callback")[0], 200)
        _, result = self.call("operation.get", operation_id=operation_id)
        self.assertEqual(result["result"]["transcription"]["status"], "failed")
        self.call("operation.cancel", operation_id=operation_id)
        self.assertEqual(handle_action(self.root, body, workspace_id="default", surface="dependency_backend_request_callback")[0], 200)
        _, result = self.call("operation.get", operation_id=operation_id)
        self.assertEqual(result["status"], "cancelled")

    def test_only_user_backend_can_create_or_complete_sharing(self):
        for surface, runtime in [("mcp", None), ("cli", None), ("backend", "runtime-one"), (None, None)]:
            with self.subTest(surface=surface, runtime=runtime):
                status, result = handle_action(self.root, {"action": "companion.connect"}, workspace_id="default", user_id="alice", surface=surface, runtime_session_id=runtime)
                self.assertEqual((status, result["error"]), (403, "user_connector_required"))

    def test_secrets_are_hashed_and_absent_from_agent_projections(self):
        credentials = self.sharing()
        status, result = mcp_result_for_tool(self.root, "browser_companion_status", {}, workspace_id="default", user_id="alice", surface="mcp")
        self.assertEqual(status, 200)
        self.assertNotIn(credentials["connector_secret"], json.dumps(result))
        with database(self.root) as db:
            row = db.execute("SELECT secret_hash FROM connections").fetchone()
            self.assertEqual(len(row["secret_hash"]), 64)
            self.assertNotEqual(row["secret_hash"], credentials["connector_secret"])
        self.assertEqual((self.root / "companion.sqlite3").stat().st_mode & 0o777, 0o600)

    def test_read_is_queued_and_only_claimed_connector_can_complete(self):
        credentials = self.sharing()
        status, queued = self.call("content.read", session_id=credentials["session_id"], max_chars=500)
        self.assertEqual((status, queued["status"]), (202, "queued"))
        self.assertNotIn("result", queued)
        _, result = self.call("companion.poll", **credentials, url="https://www.instagram.com/martagiunti/")
        command = result["command"]
        claim = {**credentials, "operation_id": command["operation_id"], "lease_id": command["lease_id"]}
        status, _ = self.call("companion.complete", **{**claim, "lease_id": "wrong"}, result={"text": "Forged"})
        self.assertEqual(status, 403)
        status, result = self.call("companion.complete", **claim, result={"text": "Observed caption"})
        self.assertEqual((status, result["status"]), (200, "completed"))
        _, operation = self.call("operation.get", operation_id=queued["operation_id"])
        self.assertEqual(operation["result"]["text"], "Observed caption")
        self.assertEqual(operation["data_class"], "personal")
        status, _ = self.call("companion.complete", **claim, result={"text": "Late overwrite"})
        self.assertEqual(status, 409)

    def test_actor_and_workspace_cannot_observe_another_shared_connection(self):
        credentials = self.sharing()
        for workspace_id, user_id in [("other", "alice"), ("default", "bob")]:
            status, result = handle_action(self.root, {"action": "content.read", "session_id": credentials["session_id"]}, workspace_id=workspace_id, user_id=user_id)
            self.assertEqual(status, 404)
            status, overview = handle_action(self.root, {"action": "companion.overview"}, workspace_id=workspace_id, user_id=user_id)
            self.assertEqual((status, overview["connections"]), (200, []))

    def test_revocation_cancels_work_and_cannot_be_resurrected_by_old_client(self):
        credentials = self.sharing()
        _, queued = self.call("content.read", session_id=credentials["session_id"])
        _, lease = self.call("companion.poll", **credentials, url="https://www.instagram.com/martagiunti/")
        self.call("companion.disconnect", session_id=credentials["session_id"])
        _, result = self.call("operation.get", operation_id=queued["operation_id"])
        self.assertEqual(result["status"], "cancelled")
        status, _ = self.call("companion.complete", **credentials, operation_id=queued["operation_id"], lease_id=lease["command"]["lease_id"], result={"text": "late"})
        self.assertEqual(status, 410)
        status, _ = self.call("companion.poll", **credentials, url="https://www.instagram.com/martagiunti/")
        self.assertEqual(status, 410)
        status, _ = self.call("companion.disconnect", session_id=credentials["session_id"])
        self.assertEqual(status, 200)

    def test_expired_connection_and_command_leases_fail_closed(self):
        credentials = self.sharing()
        _, queued = self.call("content.read", session_id=credentials["session_id"])
        _, lease = self.call("companion.poll", **credentials, url="https://www.instagram.com/martagiunti/")
        with database(self.root) as db:
            db.execute("UPDATE operations SET lease_until=?", (time.time() - 1,))
        status, _ = self.call("companion.complete", **credentials, operation_id=queued["operation_id"], lease_id=lease["command"]["lease_id"], result={"text": "late"})
        self.assertEqual(status, 409)
        _, operation = self.call("operation.get", operation_id=queued["operation_id"])
        self.assertEqual(operation["status"], "expired")
        with database(self.root) as db:
            db.execute("UPDATE connections SET expires_at=?", (time.time() - 1,))
        status, _ = self.call("content.read", session_id=credentials["session_id"])
        self.assertEqual(status, 409)

    def test_navigation_only_accepts_explicit_instagram_read_routes(self):
        for url in ["http://www.instagram.com/marta/", "https://instagram.com/marta/", "https://www.instagram.com@127.0.0.1/marta/", "https://www.instagram.com/direct/", "https://www.instagram.com/accounts/login/", "https://www.instagram.com/marta/%2e%2e/", "file:///tmp/private", "https://www.instagram.com:9323/marta/"]:
            with self.subTest(url=url), self.assertRaises(BrowserValidationError):
                instagram_url(url)
        self.assertEqual(instagram_url("https://www.instagram.com/p/AbC_12/?token=private"), "https://www.instagram.com/p/AbC_12/")

    def test_expired_connection_cannot_refresh_or_complete_live_operation(self):
        credentials = self.sharing()
        self.call("content.read", session_id=credentials["session_id"])
        _, poll = self.call("companion.poll", **credentials, url="https://www.instagram.com/martagiunti/")
        with database(self.root) as db:
            db.execute("UPDATE connections SET expires_at=?", (time.time() - 1,))
        claim = {**credentials, "operation_id": poll["command"]["operation_id"], "lease_id": poll["command"]["lease_id"]}
        self.assertEqual(self.call("companion.progress", **claim, phase="late")[0], 410)
        self.assertEqual(self.call("companion.complete", **claim, result={"text": "late"})[0], 410)

    def test_no_social_write_or_arbitrary_script_is_queued(self):
        credentials = self.sharing()
        for action, body in [("click", {}), ("type", {"text": "message"}), ("content.read", {"script": "document.cookie"}), ("scroll", {"selector": "input"}), ("video.analyze", {"max_seconds": 181})]:
            status, _ = self.call(action, session_id=credentials["session_id"], **body)
            self.assertEqual(status, 400)
        with database(self.root) as db:
            self.assertEqual(db.execute("SELECT count(*) FROM operations").fetchone()[0], 0)

    def test_poll_has_one_claim_and_queue_is_bounded(self):
        credentials = self.sharing()
        for _ in range(16):
            status, _ = self.call("content.read", session_id=credentials["session_id"])
            self.assertEqual(status, 202)
        status, _ = self.call("content.read", session_id=credentials["session_id"])
        self.assertEqual(status, 429)
        _, first = self.call("companion.poll", **credentials, url="https://www.instagram.com/martagiunti/")
        self.assertIsNotNone(first["command"])
        _, second = self.call("companion.poll", **credentials, url="https://www.instagram.com/martagiunti/")
        self.assertIsNone(second["command"])
