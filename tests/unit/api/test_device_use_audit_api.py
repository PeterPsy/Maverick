from dataclasses import replace
import unittest

from core.device_use.evidence import DeviceUseEvidenceArchive
from core.device_use.models import DeviceUseInvocationJournalRecord
from core.runtime.private_payload_store import EncryptedRuntimePrivatePayloadStore
from core.runtime.runtime_threads import create_runtime_thread
from tests.unit.api import test_device_use_reconnection as fixtures


class DeviceUseAuditApiTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.DeviceUseReconnectionTestCase()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        f = self.fixture
        turn = f._turn("completed")
        create_runtime_thread(f.state.runtime_store, workspace_id="default", runtime_session_id=f.session_id,
                              thread_id=f.session_id, agent_label="chat", source_app_id="chat")
        archive = DeviceUseEvidenceArchive(store=f.state.runtime_store, payload_store=EncryptedRuntimePrivatePayloadStore(
            repository_root=f.root, key_loader=lambda: b"k" * 32))
        f.state.device_use_service.evidence_archive = archive
        record = DeviceUseInvocationJournalRecord(
            invocation_id="audit-invocation", activation_id=f.original["activation_id"], runtime_session_id=f.session_id,
            turn_id=turn.turn_id, call_id="audit-call", tool_name="mac_project", action="verify_media",
            arguments_digest="a" * 64, effect_class="read", status="completed", dispatched_at=turn.created_at,
            updated_at=turn.created_at, native_success=True, result_valid=False)
        archive.capture(binding=f.before.device_use_binding, record=record, arguments={"source": "output/final.mp4"},
                        result={"success": True, "contentItems": [{"type": "inputText", "text": "verification-evidence"}]})
        self.path = f"/api/runtime/turns/{turn.turn_id}/device-use-audit?call_id=audit-call"

    def test_owner_reads_private_evidence_through_authenticated_no_store_route(self):
        f = self.fixture
        status, payload, headers = f._invoke(f.app, path=self.path, cookie=f.cookie)
        self.assertEqual(status, 200, payload)
        self.assertIn("verification-evidence", payload["content"])
        self.assertEqual(headers["Cache-Control"], "no-store")
        self.assertFalse(payload["has_image"])

    def test_route_requires_login_and_rejects_missing_calls_and_bad_offsets(self):
        f = self.fixture
        self.assertEqual(f._invoke(f.app, path=self.path)[0], 401)
        self.assertEqual(f._invoke(f.app, path=self.path.replace("audit-call", "unknown"), cookie=f.cookie)[0], 404)
        self.assertEqual(f._invoke(f.app, path=self.path + "&offset=bad", cookie=f.cookie)[0], 400)

    def test_platform_admin_can_inspect_evidence_for_a_different_thread_owner(self):
        f = self.fixture
        f.state.runtime_store.save_session(replace(f.before, owner_user_id="different-owner"))
        status, _payload, _headers = f._invoke(f.app, path=self.path, cookie=f.cookie)
        self.assertEqual(status, 200)
