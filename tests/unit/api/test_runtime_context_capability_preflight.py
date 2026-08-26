from __future__ import annotations

import tempfile
import unittest
from unittest.mock import patch

from core.api.platform_host import PlatformHost
from core.api.platform_state import bootstrap_platform_state
from core.providers.errors import CapabilityCertificateError
from tests.unit.api.app_reference_test_support import AppReferenceApiTestSupport


class RuntimeContextCapabilityPreflightApiTest(AppReferenceApiTestSupport, unittest.TestCase):
    def test_malformed_context_fails_before_claim_session_or_provider_work(self) -> None:
        cases = (
            ({"skill_ids": {"skill_id": "browser-value"}}, "agentic_skill_metadata_invalid"),
            ({"attachments": "browser-attachment"}, "agentic_attachment_metadata_invalid"),
            ({"app_references": ["crm"]}, "agentic_app_reference_metadata_invalid"),
        )
        for context_fields, reason_code in cases:
            with self.subTest(reason_code=reason_code), tempfile.TemporaryDirectory() as temp_dir:
                state, app, cookie = self._platform(temp_dir)
                before = state.runtime_store.list_all_sessions()
                with patch.object(
                    state.runtime_store,
                    "claim_client_message_id",
                    wraps=state.runtime_store.claim_client_message_id,
                ) as claim, patch(
                    "core.api.runtime_api.create_runtime_session",
                ) as create_session, patch(
                    "core.api.runtime_api.submit_runtime_turn",
                ) as submit_sync, patch(
                    "core.api.runtime_api.submit_runtime_turn_async",
                ) as submit_async:
                    status, payload, _headers = self._invoke(
                        app,
                        path="/api/runtime/sessions",
                        method="POST",
                        body={
                            "agent_id": "chat",
                            "source_app_id": "chat",
                            "runtime_mode": "agentic",
                            "input_text": "must not persist",
                            "client_message_id": f"malformed-{reason_code}",
                            **context_fields,
                        },
                        cookie=cookie,
                    )

                self.assertEqual(status, 409)
                self.assertEqual(payload["error"], reason_code)
                claim.assert_not_called()
                create_session.assert_not_called()
                submit_sync.assert_not_called()
                submit_async.assert_not_called()
                self.assertEqual(state.runtime_store.list_all_sessions(), before)

    def test_unsupported_context_fails_before_claim_session_or_provider_work(self) -> None:
        cases = (
            (
                {"skill_ids": ["uncertified-skill"]},
                "agentic_skill_catalog_not_effective",
            ),
            (
                {"attachments": [{"content_type": "image/png"}]},
                "agentic_attachment_modality_not_certified",
            ),
            (
                {"app_references": [{"app_id": "crm"}]},
                "agentic_app_references_not_effective",
            ),
        )
        for context_fields, reason_code in cases:
            with self.subTest(reason_code=reason_code), tempfile.TemporaryDirectory() as temp_dir:
                state, app, cookie = self._platform(temp_dir)
                before = state.runtime_store.list_all_sessions()
                with patch(
                    "core.api.runtime_api.preflight_execution_binding_context",
                    side_effect=CapabilityCertificateError(reason_code),
                ), patch.object(
                    state.runtime_store,
                    "claim_client_message_id",
                    wraps=state.runtime_store.claim_client_message_id,
                ) as claim, patch(
                    "core.api.runtime_api.create_runtime_session",
                ) as create_session, patch(
                    "core.api.runtime_api.submit_runtime_turn",
                ) as submit_sync, patch(
                    "core.api.runtime_api.submit_runtime_turn_async",
                ) as submit_async:
                    status, payload, _headers = self._invoke(
                        app,
                        path="/api/runtime/sessions",
                        method="POST",
                        body={
                            "agent_id": "chat",
                            "source_app_id": "chat",
                            "runtime_mode": "agentic",
                            "input_text": "must not persist",
                            "client_message_id": f"blocked-{reason_code}",
                            **context_fields,
                        },
                        cookie=cookie,
                    )

                self.assertEqual(status, 409)
                self.assertEqual(payload["error"], reason_code)
                claim.assert_not_called()
                create_session.assert_not_called()
                submit_sync.assert_not_called()
                submit_async.assert_not_called()
                self.assertEqual(state.runtime_store.list_all_sessions(), before)

    def _platform(self, temp_dir: str):
        repo_root = self._repo_root(temp_dir)
        with patch.dict(
            "os.environ",
            {
                "MAVERICK_ALLOW_INSECURE_TEST_DEFAULTS": "1",
                "MAVERICK_ADMIN_USERNAME": "admin",
                "MAVERICK_ADMIN_PASSWORD": "maverick",
            },
        ):
            state = bootstrap_platform_state(start_path=repo_root)
        app = PlatformHost(state, start_path=repo_root)
        return state, app, self._login(app)


if __name__ == "__main__":
    unittest.main()
