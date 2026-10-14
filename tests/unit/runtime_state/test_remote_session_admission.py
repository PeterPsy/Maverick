"""RemoteSessionAdmissionTests fixtures extracted without changing assertions."""

from __future__ import annotations
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch
from core.providers.agentic_data_policies import (
    REMOTE_FULL_WORKSPACE_EGRESS_POLICY_ID,
    REMOTE_FULL_WORKSPACE_EGRESS_POLICY_REVISION,
)
from core.providers.errors import AgenticProfileError
from core.runtime.agentic_feature_flags import (
    LOOPINO_FEATURE_ANTIGRAVITY_AGENTIC_PREVIEW,
    LOOPINO_FEATURE_GOOGLE_AGENTIC_PREVIEW,
    LOOPINO_FEATURE_HOSTED_AGENT_RUNTIME,
    LOOPINO_FEATURE_OPENROUTER_AGENTIC_PREVIEW,
)
from core.runtime.hosted_agentic_models import HostedAgenticLoopError
from core.runtime.lifecycle_service import create_runtime_session
from core.runtime.remote_agentic_admission import (
    require_remote_agentic_dispatch,
    require_remote_agentic_session_admission,
)
from tests.unit.runtime_state.remote_admission_fixture import _identity, _remote_environment


class RemoteSessionAdmissionTests(unittest.TestCase):
    def test_openrouter_full_workspace_policy_needs_no_fake_attestation(self) -> None:
        identity = SimpleNamespace(
            **vars(_identity("openrouter")),
            egress_policy_id=REMOTE_FULL_WORKSPACE_EGRESS_POLICY_ID,
            egress_policy_revision=REMOTE_FULL_WORKSPACE_EGRESS_POLICY_REVISION,
        )
        workspace_store = Mock()
        with patch.dict(
            "os.environ",
            _remote_environment("openrouter"),
            clear=True,
        ), patch(
            "core.runtime.remote_agentic_admission.REMOTE_AGENTIC_ATTESTATION_AVAILABLE",
            False,
        ):
            require_remote_agentic_session_admission(
                identity,
                workspace_id="workspace-1",
                workspace_store=workspace_store,
            )
        workspace_store.get_data_attestation.assert_not_called()

    def test_antigravity_requires_its_independent_preview_flag(self) -> None:
        identity = SimpleNamespace(
            runtime_engine_id="antigravity-cli",
            adapter_id="antigravity-cli-stream-json",
            model_provider_id="google",
            provider_protocol="antigravity-cli-stream-json",
        )
        environment = {
            LOOPINO_FEATURE_HOSTED_AGENT_RUNTIME: "1",
            LOOPINO_FEATURE_ANTIGRAVITY_AGENTIC_PREVIEW: "0",
        }
        with patch.dict("os.environ", environment, clear=True):
            with self.assertRaisesRegex(
                AgenticProfileError,
                "antigravity_agentic_preview_disabled",
            ):
                require_remote_agentic_session_admission(identity)

        environment[LOOPINO_FEATURE_ANTIGRAVITY_AGENTIC_PREVIEW] = "1"
        with patch.dict("os.environ", environment, clear=True):
            with self.assertRaisesRegex(
                AgenticProfileError,
                "remote_agentic_attestation_required",
            ):
                require_remote_agentic_session_admission(identity)

    def test_google_and_openrouter_sessions_fail_before_any_store_call(self) -> None:
        for provider_id in ("google-ai-studio", "openrouter"):
            with self.subTest(provider_id=provider_id), patch.dict("os.environ", {}, clear=True):
                store = Mock()
                with self.assertRaises(AgenticProfileError) as raised:
                    create_runtime_session(
                        store,
                        session_id=f"session-{provider_id}",
                        workspace_id="default",
                        agent_id="chat",
                        runtime_mode="agentic",
                        execution_binding=_identity(provider_id),
                    )
                self.assertEqual(str(raised.exception), "hosted_agent_runtime_disabled")
                store.assert_not_called()
                self.assertEqual(store.method_calls, [])

    def test_client_fake_declaration_never_authorizes_remote_session(self) -> None:
        environment = {
            LOOPINO_FEATURE_HOSTED_AGENT_RUNTIME: "1",
            LOOPINO_FEATURE_GOOGLE_AGENTIC_PREVIEW: "1",
        }
        with patch.dict("os.environ", environment, clear=True):
            with self.assertRaises(AgenticProfileError) as raised:
                require_remote_agentic_session_admission(
                    _identity("google-ai-studio"),
                    declared_remote_data_class="workspace_internal_fake",
                )
        self.assertEqual(str(raised.exception), "remote_data_declaration_not_accepted")

        with patch.dict("os.environ", environment, clear=True):
            with self.assertRaises(AgenticProfileError) as raised:
                require_remote_agentic_session_admission(_identity("google-ai-studio"))
        self.assertEqual(str(raised.exception), "remote_agentic_attestation_required")

    def test_unknown_hosted_provider_fails_closed_even_when_known_flags_are_on(self) -> None:
        environment = {
            LOOPINO_FEATURE_HOSTED_AGENT_RUNTIME: "1",
            LOOPINO_FEATURE_GOOGLE_AGENTIC_PREVIEW: "1",
            LOOPINO_FEATURE_OPENROUTER_AGENTIC_PREVIEW: "1",
        }
        with patch.dict("os.environ", environment, clear=True):
            with self.assertRaises(HostedAgenticLoopError) as raised:
                require_remote_agentic_dispatch(_identity("future-provider"))
        self.assertEqual(raised.exception.reason_code, "remote_agentic_provider_unapproved")
