from dataclasses import replace
import json
from pathlib import Path
import unittest

from core.device_use.audit import read_device_use_audit, read_device_use_call, device_use_call_image
from core.device_use.evidence import DeviceUseEvidenceArchive
from core.device_use.models import DeviceUseInvocationJournalRecord
from core.device_use.result_facts import native_result_facts
from core.runtime.errors import RuntimeTranscriptAccessError, RuntimeTranscriptValidationError
from core.runtime.private_payload_store import EncryptedRuntimePrivatePayloadStore
from tests.unit.runtime_threads import test_runtime_transcripts as fixtures
from tests.unit.device_use import test_device_use_service as service_fixtures
from tests.support.repo import make_temp_repo_root


class DeviceUseAuditTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.RuntimeTranscriptTest()
        self.store = self.fixture.memory_store()
        _service, binding, _outbound = service_fixtures.DeviceUseServiceTestCase().connected()
        self.binding = replace(binding, owner_user_id="alice")
        self.session = replace(self.fixture.session("session-1"), device_use_binding=self.binding)
        self.fixture.seed_conversation(self.store, session=self.session)
        self.root = make_temp_repo_root(self)
        self.archive = DeviceUseEvidenceArchive(store=self.store, payload_store=EncryptedRuntimePrivatePayloadStore(
            repository_root=self.root, key_loader=lambda: b"k" * 32))

    def capture(self, call_id, **extra):
        record = DeviceUseInvocationJournalRecord(
            invocation_id=f"invocation-{call_id}", activation_id=self.binding.activation_id,
            runtime_session_id=self.session.session_id, turn_id="turn-1", call_id=call_id,
            tool_name="mac_project", action="verify_media", arguments_digest="a" * 64,
            effect_class="read", status="completed", dispatched_at=fixtures.NOW,
            updated_at=fixtures.NOW, native_duration_ms=1000, native_user_wait_ms=200,
            native_success=True, result_valid=False)
        self.archive.capture(binding=self.binding, record=record, **extra)

    def read_call(self, **overrides):
        args = dict(archive=self.archive, context=self.fixture.context(), thread_id="session-1",
                    turn_id="turn-1", call_id="one")
        args.update(overrides)
        return read_device_use_call(self.store, **args)

    def test_evidence_is_encrypted_and_typed_text_is_withheld(self):
        self.capture("one", arguments={"source": "private-project.mp4", "text": "secret-typed-text"},
                     result={"success": True, "contentItems": [{"type": "inputText", "text": "private-native-result"}]})
        persisted = "".join(p.read_text() for p in Path(self.root).rglob("*.json"))
        self.assertNotIn("private-native-result", persisted)
        self.assertNotIn("private-project.mp4", persisted)
        self.assertNotIn("secret-typed-text", persisted)
        page = self.read_call(max_chars=50)
        self.assertTrue(page["has_more"])
        full = self.read_call()
        self.assertIn("private-native-result", full["content"])
        self.assertIn("[typed text withheld]", full["content"])
        self.assertNotIn("secret-typed-text", full["content"])
        tail = self.read_call(offset=page["next_offset"])
        self.assertEqual(page["content"] + tail["content"], full["content"])

    def test_calls_paginate_and_distinguish_native_success_from_invalid_media(self):
        for name in ["one", "two", "three"]:
            self.capture(name, result={"success": True})
        latest = read_device_use_audit(self.store, context=self.fixture.context(), thread_id="session-1", limit=2)
        self.assertEqual([c["call_id"] for c in latest["calls"]], ["two", "three"])
        first = read_device_use_audit(self.store, context=self.fixture.context(), thread_id="session-1", limit=2,
                                     before_cursor=latest["page"]["before_cursor"])
        self.assertEqual([c["call_id"] for c in first["calls"]], ["one"])
        metrics = latest["turns"][0]
        self.assertEqual(metrics["native_execution_ms"], 2400)
        self.assertEqual(metrics["native_user_wait_ms"], 600)
        self.assertEqual(metrics["outside_native_ms"], 2000)
        self.assertEqual(metrics["failed_count"], 0)
        self.assertEqual(metrics["invalid_result_count"], 3)
        with self.assertRaises(RuntimeTranscriptValidationError):
            read_device_use_audit(self.store, context=self.fixture.context(), thread_id="session-1", before_cursor="unknown")

    def test_cross_owner_workspace_and_turn_access_fail_closed(self):
        self.capture("one", result={"success": True})
        for context in [self.fixture.context("bob"), self.fixture.context(workspace_id="another")]:
            with self.assertRaises(RuntimeTranscriptAccessError):
                self.read_call(context=context)
        with self.assertRaises(RuntimeTranscriptAccessError):
            self.read_call(turn_id="another-turn")

    def test_observation_success_retains_uncertain_input_and_new_metric_coverage(self):
        self.capture("one", result={"success": True, "contentItems": [{"text": "action_outcome=indeterminate; observation_succeeded=true; input_effect_confirmed=false"}]})
        self.store.save_event(self.fixture.event("delivery", "runtime.tool_call.completed", {
            "tool_kind": "device_use", "call_id": "one", "name": "mac_project", "action": "verify_media",
            "outcome_state": "indeterminate", "native_success": True,
            "provider_observation_delivery_ms": 25, "result_text_char_count": 100}))
        result = read_device_use_audit(self.store, context=self.fixture.context(), thread_id="session-1")
        self.assertEqual(result["turns"][0]["uncertain_outcome_count"], 1)
        self.assertEqual(result["turns"][0]["provider_observation_delivery_ms"], 25)
        self.assertEqual(result["turns"][0]["result_text_char_count"], 100)
        self.assertIsNone(result["turns"][0]["outside_bridge_ms"])
        self.assertEqual(result["turns"][0]["metric_measured_call_counts"]["bridge_end_to_end_ms"], 0)

    def test_image_chunks_round_trip_with_integrity_and_are_not_public_payloads(self):
        jpeg = b"\xff\xd8" + b"x" * 1_100_000 + b"\xff\xd9"
        self.capture("one", result={"success": True}, jpeg=jpeg)
        self.assertTrue(self.read_call()["has_image"])
        image = device_use_call_image(self.store, archive=self.archive, context=self.fixture.context(),
                                     thread_id="session-1", turn_id="turn-1", call_id="one")
        self.assertEqual(image, jpeg)
        for event in self.store.list_events("session-1"):
            self.assertNotIn("contentItems", event.payload)
            self.assertNotIn("image_refs", event.payload)

    def test_missing_private_evidence_is_explicit_and_never_falls_back_to_provider_logs(self):
        self.capture("one", result={"success": True})
        for path in Path(self.root).rglob("*.json"):
            path.unlink()
        with self.assertRaisesRegex(RuntimeTranscriptAccessError, "device_use_evidence_unavailable"):
            self.read_call()

    def test_result_facts_keep_media_rejection_separate_and_parse_script_validity(self):
        facts = native_result_facts({"success": True, "contentItems": [{"text": json.dumps(
            {"verification": {"valid": False}})}]})
        self.assertTrue(facts["native_success"])
        self.assertFalse(facts["result_valid"])
        facts = native_result_facts({"success": False, "contentItems": [{"text": "MC-PEEKABOO-21: action_outcome=partial"}]})
        self.assertEqual(facts["failure_reason_code"], "MC-PEEKABOO-21")
        self.assertEqual(facts["outcome_state"], "partial")

    def test_native_uncertainty_diagnostics_preserve_outcome_without_a_text_marker(self):
        for code, outcome in {20: "dispatched_unverified", 21: "indeterminate",
                              22: "partial", 23: "suspected_noop"}.items():
            with self.subTest(code=code):
                facts = native_result_facts({"success": False, "contentItems": [
                    {"text": f"MC-PEEKABOO-{code}: non ripetere; osservare la stessa app."}]})
                self.assertEqual(facts["outcome_state"], outcome)
        facts = native_result_facts({"success": False, "contentItems": [{"text": "MC-PEEKABOO-01: unknown"}]})
        self.assertIsNone(facts["outcome_state"])

    def test_legacy_and_mixed_history_report_missing_measurements_as_unavailable(self):
        self.store.save_event(self.fixture.event("legacy-call", "runtime.tool_call.completed", {
            "tool_kind": "device_use", "tool_call_id": "legacy", "name": "mac_project",
            "action": "verify_media", "native_duration_ms": 500,
        }))
        for mixed in [False, True]:
            with self.subTest(mixed=mixed):
                if mixed:
                    self.capture("new", result={"success": True})
                metrics = read_device_use_audit(self.store, context=self.fixture.context(),
                                               thread_id="session-1")["turns"][0]
                self.assertEqual(metrics["native_duration_ms"], 1500 if mixed else 500)
                self.assertIsNone(metrics["native_user_wait_ms"])
                self.assertIsNone(metrics["native_execution_ms"])
                self.assertIsNone(metrics["image_count"])
                self.assertIsNone(metrics["bridge_overhead_ms"])
                self.assertIn("native_user_wait_ms", metrics["unavailable_metrics"])
                self.assertEqual(metrics["metric_measured_call_counts"]["native_user_wait_ms"], int(mixed))
                self.assertIsNone(metrics["by_action"]["mac_project.verify_media"]["native_user_wait_ms"])
