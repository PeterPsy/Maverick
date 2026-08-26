"""Phase-0 fail-closed remote agentic admission contracts."""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from core.providers.errors import AgenticProfileError
from core.runtime.agentic_feature_flags import (
    MAVERICK_FEATURE_GOOGLE_AGENTIC_PREVIEW,
    MAVERICK_FEATURE_HOSTED_AGENT_RUNTIME,
    MAVERICK_FEATURE_OPENROUTER_AGENTIC_PREVIEW,
)
from core.runtime.hosted_agentic_models import HostedAgenticLoopError
from core.runtime.errors import RuntimeTurnQueueRejectedError
from core.runtime.lifecycle_service import create_runtime_session
from core.runtime.remote_agentic_admission import (
    require_remote_agentic_dispatch,
    require_remote_agentic_session_admission,
)
from core.runtime.runtime_session import RuntimeSessionRecord
from core.runtime.turn_queue_admission import require_turn_queue_session_executable
from core.workspaces.data_governance import (
    issue_fake_data_attestation,
    revoke_data_attestation,
)


def _identity(provider_id: str):
    return SimpleNamespace(
        runtime_engine_id="hosted-agent-runtime",
        adapter_id="hosted-agent-adapter",
        model_provider_id=provider_id,
        provider_protocol=f"{provider_id}-agentic-v1",
    )


class RemoteAgenticAdmissionTest(unittest.TestCase):
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
            MAVERICK_FEATURE_HOSTED_AGENT_RUNTIME: "1",
            MAVERICK_FEATURE_GOOGLE_AGENTIC_PREVIEW: "1",
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
        self.assertEqual(str(raised.exception), "remote_agentic_attestation_unavailable")

    def test_unknown_hosted_provider_fails_closed_even_when_known_flags_are_on(self) -> None:
        environment = {
            MAVERICK_FEATURE_HOSTED_AGENT_RUNTIME: "1",
            MAVERICK_FEATURE_GOOGLE_AGENTIC_PREVIEW: "1",
            MAVERICK_FEATURE_OPENROUTER_AGENTIC_PREVIEW: "1",
        }
        with patch.dict("os.environ", environment, clear=True):
            with self.assertRaises(HostedAgenticLoopError) as raised:
                require_remote_agentic_dispatch(_identity("future-provider"))
        self.assertEqual(raised.exception.reason_code, "remote_agentic_provider_unapproved")

    def test_certified_attestation_gate_requires_active_matching_workspace_record(self) -> None:
        environment = {
            MAVERICK_FEATURE_HOSTED_AGENT_RUNTIME: "1",
            MAVERICK_FEATURE_GOOGLE_AGENTIC_PREVIEW: "1",
        }
        active = issue_fake_data_attestation(
            workspace_id="workspace-1",
            actor_id="operator-1",
            actor_kind="platform_operator",
            scope_type="workspace",
            expected_revision=0,
            now=datetime(2026, 8, 26, tzinfo=UTC),
        )
        revoked = revoke_data_attestation(
            active,
            actor_id="operator-2",
            expected_revision=1,
            reason="fixture retired",
            now=datetime(2026, 8, 26, tzinfo=UTC),
        )
        with patch.dict("os.environ", environment, clear=True), patch(
            "core.runtime.remote_agentic_admission.REMOTE_AGENTIC_ATTESTATION_AVAILABLE",
            True,
        ):
            with self.assertRaisesRegex(
                AgenticProfileError,
                "remote_agentic_attestation_required",
            ):
                require_remote_agentic_session_admission(
                    _identity("google-ai-studio"),
                    workspace_id="workspace-1",
                )
            require_remote_agentic_session_admission(
                _identity("google-ai-studio"),
                workspace_id="workspace-1",
                workspace_attestation=active,
            )
            with self.assertRaisesRegex(
                AgenticProfileError,
                "remote_agentic_attestation_workspace_mismatch",
            ):
                require_remote_agentic_session_admission(
                    _identity("google-ai-studio"),
                    workspace_id="workspace-2",
                    workspace_attestation=active,
                )
            with self.assertRaisesRegex(
                AgenticProfileError,
                "remote_agentic_attestation_revoked",
            ):
                require_remote_agentic_session_admission(
                    _identity("google-ai-studio"),
                    workspace_id="workspace-1",
                    workspace_attestation=revoked,
                )

    def test_codex_and_plain_hosted_text_are_not_remote_agentic(self) -> None:
        codex = SimpleNamespace(
            runtime_engine_id="codex",
            adapter_id="codex-app-server",
            model_provider_id="codex",
            provider_protocol="codex-app-server-stdio",
        )
        with patch.dict("os.environ", {}, clear=True):
            require_remote_agentic_session_admission(codex)
            require_remote_agentic_dispatch(codex)
            require_remote_agentic_session_admission(None)
            require_remote_agentic_dispatch(None)
        with self.assertRaisesRegex(
            AgenticProfileError,
            "remote_data_declaration_not_accepted",
        ):
            require_remote_agentic_session_admission(
                codex,
                declared_remote_data_class="public",
            )

    def test_codex_like_but_non_exact_identities_are_remote_and_fail_closed(self) -> None:
        for adapter_id, protocol in (
            ("hosted-impostor", "codex-app-server-stdio"),
            ("codex-app-server", "hosted-codex-compatible"),
        ):
            identity = SimpleNamespace(
                runtime_engine_id="codex",
                adapter_id=adapter_id,
                model_provider_id="codex",
                provider_protocol=protocol,
            )
            with self.subTest(adapter_id=adapter_id, protocol=protocol), patch.dict(
                "os.environ", {}, clear=True
            ), self.assertRaisesRegex(
                AgenticProfileError,
                "hosted_agent_runtime_disabled",
            ):
                require_remote_agentic_session_admission(identity)

    def test_recovery_required_and_contained_pins_have_explicit_queue_reasons(self) -> None:
        base = dict(
            session_id="session-contained",
            workspace_id="default",
            agent_id="chat",
            status="recovery_required",
            requested_mode="sandbox",
            effective_mode="sandbox",
            workspace_root="/workspace",
            workdir="/workspace",
            runtime_root="/runtime/session-contained",
            started_at=None,
            updated_at=datetime.now(UTC),
            ended_at=None,
            last_progress_at=None,
            execution_binding=_identity("google-ai-studio"),
            recovery_reason_code="remote_agentic_state_ambiguous",
        )
        session = RuntimeSessionRecord(**base)
        with self.assertRaises(RuntimeTurnQueueRejectedError) as raised:
            require_turn_queue_session_executable(Mock(), session)
        self.assertEqual(raised.exception.reason_code, "runtime_session_recovery_required")

        running = RuntimeSessionRecord(**{**base, "status": "running"})
        with patch.dict("os.environ", {}, clear=True), self.assertRaises(
            RuntimeTurnQueueRejectedError
        ) as raised:
            require_turn_queue_session_executable(Mock(), running)
        self.assertEqual(raised.exception.reason_code, "remote_agentic_session_contained")


if __name__ == "__main__":
    unittest.main()
