"""Production-composed submission with only the external HTTP peer fabricated.

These are offline regressions, not a laboratory grant or natural evidence.
Admission, certificates, actor/egress authority, codecs and persistence are real.
"""

import io
import json
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from core.api.runtime_api import _create_session, _preflight_runtime_session_creation_before_persistence
from core.runtime import runtime_process_lifecycle
from core.runtime.public_content_authority_store import issue_runtime_public_content_authority
from core.runtime.turn_submission_service_events import _record_final_output
from core.runtime.turn_submission_service_submit import submit_runtime_turn
from core.secrets.service import create_platform_secret
from core.workspaces.data_governance import revoke_data_attestation
from tests.support.remote_admission_path import admitted_fixture
from tests.unit.providers.test_openrouter_agentic_catalog import _model_catalog, _zdr_catalog
from tests.unit.providers.test_openrouter_agentic_codec import _text_stream


class _Response(io.BytesIO):
    def __init__(self, content, url, content_type):
        super().__init__(content)
        self.url = url
        self.headers = {"Content-Type": content_type}

    def geturl(self):
        return self.url


class RemoteFullSubmissionTest(unittest.TestCase):
    def setUp(self):
        self.network = self.enterContext(patch("socket.socket.connect", side_effect=AssertionError("real network forbidden")))
        self.state, self.binding, self.attestation = admitted_fixture(self)
        self.posts = []
        self.catalog_reads = 0
        # Test-only bytes, in the disposable fixture's own vault and workspace.
        create_platform_secret(self.state.secret_store, label="Offline test token", secret_id="offline-only",
                               raw_value="not-a-provider-key")
        issue_runtime_public_content_authority(self.state.workspace_store, workspace_id="default",
                                               actor_id="offline-operator", expected_revision=0)
        context = SimpleNamespace(user=self.state.identity_store.list_users()[0], workspace_id="default")
        body = {"runtime_mode": "agentic", "requested_mode": "full-access",
                "title": "Offline admission regression",
                "workspace_profile_binding_id": self.binding.workspace_binding_id}
        preflight = _preflight_runtime_session_creation_before_persistence(self.state, context, body)
        self.session = _create_session(self.state, context, body, agent_id="chat",
                                       start_path=self.state.repository_root, preflight=preflight)
        self.enterContext(patch("urllib.request.OpenerDirector.open",
                                new=lambda _opener, request, *args, **kwargs: self.open_http(request)))
        self.addCleanup(self.close_runtime_resources)

    def close_runtime_resources(self):
        # The real submission schedules a 180-second idle reaper. Drain this
        # session's real cleanup before its disposable store is removed; never
        # leave that timer to fail later in an unrelated test or mask the error.
        with runtime_process_lifecycle._IDLE_REAP_TIMERS_LOCK:
            timer = runtime_process_lifecycle._IDLE_REAP_TIMERS.get(self.session.session_id)
        before = (len(self.posts), self.catalog_reads)
        runtime_process_lifecycle.release_idle_runtime_processes(
            self.state, session_id=self.session.session_id, provider_id="maverick-tool-loop",
            reason="offline_fixture_teardown", idle_ttl_seconds=0,
        )
        if timer is not None:
            timer.join(timeout=5)
            self.assertFalse(timer.is_alive(), "fixture idle reaper survived teardown")
        self.assertEqual((len(self.posts), self.catalog_reads), before)
        self.network.assert_not_called()

    def open_http(self, request):
        url, method = request.full_url, request.get_method()
        if method == "GET" and url in {
            "https://openrouter.ai/api/v1/endpoints/zdr",
            "https://openrouter.ai/api/v1/models/deepseek/deepseek-v4-flash/endpoints",
        }:
            self.catalog_reads += 1
            catalog = _zdr_catalog() if url.endswith("/endpoints/zdr") else _model_catalog()
            return _Response(json.dumps(catalog).encode(), url, "application/json")
        if method == "POST" and url == "https://openrouter.ai/api/v1/chat/completions":
            self.posts.append(json.loads(request.data))
            body = "".join("data: " + json.dumps(item) + "\n\n" for item in _text_stream("offline-generation", "OK"))
            return _Response((body + "data: [DONE]\n\n").encode(), url, "text/event-stream")
        raise AssertionError("unexpected offline HTTP route")

    def submit(self, **kwargs):
        return submit_runtime_turn(self.state, session=self.session, input_text="Return exactly the word OK.",
                                   turn_id="full-path-offline", **kwargs)

    def test_enable_api_create_queue_dispatch_and_complete_with_real_authority(self):
        turn, _events = self.submit()
        self.assertEqual(turn.status, "completed")
        self.assertEqual(len(self.posts), 1)
        self.assertEqual(self.catalog_reads, 2)
        self.assertEqual(len(self.posts[0]["tools"]), 19)
        finals = [event for event in self.state.runtime_store.list_events(self.session.session_id)
                  if event.event_type == "runtime.output.final"]
        self.assertEqual(len(finals), 1)
        self.assertEqual(finals[0].payload["complete_text"], "OK")
        self.assertEqual(finals[0].payload["provider_id"], "openrouter")
        self.assertTrue(finals[0].payload["delivery_id"])
        expected = {"provider_id": "maverick-tool-loop", "complete_text": "OK", "exit_code": 0}
        for changes in ({"provider_id": "another-provider"}, {"complete_text": "tampered"}, {"exit_code": 1}):
            with self.subTest(changes=changes), self.assertRaisesRegex(RuntimeError, "final_output_identity_conflict"):
                _record_final_output(self.state, session_id=self.session.session_id, turn_id=turn.turn_id,
                                     output_text="OK", **{**expected, **changes})
        self.network.assert_not_called()

    def test_revocation_after_real_queue_makes_no_catalog_or_completion_request(self):
        def revoke(_turn, _events):
            self.state.workspace_store.save_data_attestation(
                revoke_data_attestation(self.attestation, actor_id="offline-operator", expected_revision=1, reason="retired"),
                expected_revision=1,
            )
        turn, _events = self.submit(on_queued=revoke)
        self.assertEqual(turn.status, "failed")
        self.assertEqual(self.posts, [])
        self.assertEqual(self.catalog_reads, 0)
        self.network.assert_not_called()


if __name__ == "__main__":
    unittest.main()
