"""Fail-closed remote agentic admission contracts."""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from core.providers.errors import AgenticProfileError, AgenticRuntimeError
from core.recovery.runtime_admission import assess_runtime_session_admission
from core.runtime.authority_service import resolve_runtime_authority_snapshot
from core.runtime.agentic_feature_flags import LOOPINO_FEATURE_GOOGLE_AGENTIC_PREVIEW, LOOPINO_FEATURE_HOSTED_AGENT_RUNTIME
from core.runtime.hosted_agentic_models import HostedAgenticLoopError
from core.runtime.errors import RuntimeTurnNotFoundError, RuntimeTurnQueueRejectedError
from core.runtime.lifecycle_service import create_runtime_session, queue_runtime_turn
from core.runtime.provider_start_handoff import runtime_provider_start_handoff
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
from tests.support.repo import make_temp_repo_root
from tests.unit.runtime_state.remote_admission_fixture import _identity, _remote_binding, _runtime_store, _AttestationStore, _remote_environment


class RemoteAgenticAdmissionTest(unittest.TestCase):


    def test_attestation_gate_requires_active_matching_workspace_record(self) -> None:
        environment = {
            LOOPINO_FEATURE_HOSTED_AGENT_RUNTIME: "1",
            LOOPINO_FEATURE_GOOGLE_AGENTIC_PREVIEW: "1",
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

    def test_malformed_persisted_attestation_fails_closed(self) -> None:
        workspace_store = SimpleNamespace(
            get_data_attestation=lambda _workspace_id: SimpleNamespace(
                workspace_id="workspace-1",
                status="active",
                authoritative=True,
                well_formed=True,
            )
        )
        with patch.dict(
            "os.environ",
            _remote_environment("google-ai-studio"),
            clear=True,
        ), self.assertRaisesRegex(
            AgenticProfileError,
            "remote_agentic_attestation_invalid",
        ):
            require_remote_agentic_session_admission(
                _identity("google-ai-studio"),
                workspace_id="workspace-1",
                workspace_store=workspace_store,
            )

    def test_persisted_attestation_overrides_a_stale_supplied_snapshot(self) -> None:
        now = datetime(2026, 9, 7, tzinfo=UTC)
        active = issue_fake_data_attestation(
            workspace_id="workspace-1",
            actor_id="operator-1",
            actor_kind="platform_operator",
            scope_type="workspace",
            expected_revision=0,
            now=now,
        )
        revoked = revoke_data_attestation(
            active,
            actor_id="operator-2",
            expected_revision=1,
            reason="authoritative store supersedes stale snapshot",
            now=now,
        )
        with patch.dict(
            "os.environ",
            _remote_environment("google-ai-studio"),
            clear=True,
        ), self.assertRaisesRegex(
            AgenticProfileError,
            "remote_agentic_attestation_revoked",
        ):
            require_remote_agentic_session_admission(
                _identity("google-ai-studio"),
                workspace_id="workspace-1",
                workspace_attestation=active,
                workspace_store=_AttestationStore(revoked),
            )

    def test_authoritative_workspace_context_reaches_create_queue_and_dispatch(self) -> None:
        now = datetime(2026, 9, 7, tzinfo=UTC)
        active = issue_fake_data_attestation(
            workspace_id="workspace-1",
            actor_id="operator-1",
            actor_kind="platform_operator",
            scope_type="workspace",
            expected_revision=0,
            now=now,
        )
        revoked = revoke_data_attestation(
            active,
            actor_id="operator-2",
            expected_revision=1,
            reason="candidate revocation fixture",
            now=now,
        )
        workspace_store = _AttestationStore(active)
        runtime_store = _runtime_store()
        binding = _remote_binding(provider_id="google-ai-studio", now=now)

        with patch.dict(
            "os.environ",
            _remote_environment("google-ai-studio"),
            clear=True,
        ), patch(
            "core.runtime.remote_agentic_admission.REMOTE_AGENTIC_ATTESTATION_AVAILABLE",
            True,
        ):
            session = create_runtime_session(
                runtime_store,
                session_id=binding.session_id,
                workspace_id=binding.workspace_id,
                agent_id="chat",
                runtime_mode="agentic",
                execution_binding=binding,
                workspace_store=workspace_store,
                now=now,
                start_path=make_temp_repo_root(self),
            )
            turn = queue_runtime_turn(
                runtime_store,
                turn_id="turn-active-attestation",
                session_id=session.session_id,
                input_text="synthetic",
                workspace_store=workspace_store,
                now=now,
            )
            self.assertEqual(turn.status, "queued")
            with runtime_provider_start_handoff(
                runtime_store,
                session_id=session.session_id,
                workspace_store=workspace_store,
            ) as (provider_session, accepted):
                self.assertEqual(provider_session.session_id, session.session_id)
                accepted({})

            workspace_store.records = [revoked]
            workspace_store.calls = 0
            with self.assertRaises(RuntimeTurnQueueRejectedError) as raised:
                queue_runtime_turn(
                    runtime_store,
                    turn_id="turn-revoked-attestation",
                    session_id=session.session_id,
                    input_text="must not persist",
                    workspace_store=workspace_store,
                    now=now,
                )
            self.assertEqual(
                raised.exception.reason_code,
                "remote_agentic_session_contained",
            )
            with self.assertRaises(RuntimeTurnNotFoundError):
                runtime_store.get_turn("turn-revoked-attestation")

    def test_provider_start_rereads_attestation_after_queue_fence(self) -> None:
        now = datetime(2026, 9, 7, tzinfo=UTC)
        active = issue_fake_data_attestation(
            workspace_id="workspace-1",
            actor_id="operator-1",
            actor_kind="platform_operator",
            scope_type="workspace",
            expected_revision=0,
            now=now,
        )
        revoked = revoke_data_attestation(
            active,
            actor_id="operator-2",
            expected_revision=1,
            reason="revoked between queue fence and dispatch",
            now=now,
        )
        workspace_store = _AttestationStore(active)
        runtime_store = _runtime_store()
        binding = _remote_binding(provider_id="openrouter", now=now)
        with patch.dict(
            "os.environ",
            _remote_environment("openrouter"),
            clear=True,
        ), patch(
            "core.runtime.remote_agentic_admission.REMOTE_AGENTIC_ATTESTATION_AVAILABLE",
            True,
        ):
            session = create_runtime_session(
                runtime_store,
                session_id=binding.session_id,
                workspace_id=binding.workspace_id,
                agent_id="chat",
                runtime_mode="agentic",
                execution_binding=binding,
                workspace_store=workspace_store,
                now=now,
                start_path=make_temp_repo_root(self),
            )
            workspace_store.records = [active, revoked]
            workspace_store.calls = 0
            with self.assertRaisesRegex(
                HostedAgenticLoopError,
                "remote_agentic_attestation_revoked",
            ):
                with runtime_provider_start_handoff(
                    runtime_store,
                    session_id=session.session_id,
                    workspace_store=workspace_store,
                ):
                    self.fail("dispatch proceeded after attestation revocation")

    def test_authority_refresh_rejects_revocation_before_adapter_work(self) -> None:
        now = datetime(2026, 9, 7, tzinfo=UTC)
        active = issue_fake_data_attestation(
            workspace_id="workspace-1",
            actor_id="operator-1",
            actor_kind="platform_operator",
            scope_type="workspace",
            expected_revision=0,
            now=now,
        )
        revoked = revoke_data_attestation(
            active,
            actor_id="operator-2",
            expected_revision=1,
            reason="authority refresh fixture",
            now=now,
        )
        binding = _remote_binding(provider_id="google-ai-studio", now=now)
        adapter = Mock()
        state = SimpleNamespace(
            workspace_store=_AttestationStore(revoked),
            provider_store=Mock(),
        )
        session = SimpleNamespace(
            execution_binding=binding,
            workspace_id=binding.workspace_id,
        )
        with patch.dict(
            "os.environ",
            _remote_environment("google-ai-studio"),
            clear=True,
        ), patch(
            "core.runtime.remote_agentic_admission.REMOTE_AGENTIC_ATTESTATION_AVAILABLE",
            True,
        ), self.assertRaisesRegex(
            AgenticRuntimeError,
            "remote_agentic_attestation_revoked",
        ):
            resolve_runtime_authority_snapshot(
                state,
                session=session,
                adapter=adapter,
                turn_id="turn-revoked-authority",
            )
        adapter.health.assert_not_called()

    def test_continuation_admission_rechecks_attestation_before_adapter_work(self) -> None:
        now = datetime(2026, 9, 7, tzinfo=UTC)
        active = issue_fake_data_attestation(
            workspace_id="workspace-1",
            actor_id="operator-1",
            actor_kind="platform_operator",
            scope_type="workspace",
            expected_revision=0,
            now=now,
        )
        revoked = revoke_data_attestation(
            active,
            actor_id="operator-2",
            expected_revision=1,
            reason="continuation admission fixture",
            now=now,
        )
        runtime_store = _runtime_store()
        binding = _remote_binding(provider_id="openrouter", now=now)
        with patch.dict(
            "os.environ",
            _remote_environment("openrouter"),
            clear=True,
        ):
            session = create_runtime_session(
                runtime_store,
                session_id=binding.session_id,
                workspace_id=binding.workspace_id,
                agent_id="chat",
                runtime_mode="agentic",
                execution_binding=binding,
                workspace_store=_AttestationStore(active),
                now=now,
                start_path=make_temp_repo_root(self),
            )
            provider_store = Mock()
            registry = Mock()
            assessment = assess_runtime_session_admission(
                provider_store,
                runtime_store,
                registry,
                session=session,
                workspace_store=_AttestationStore(revoked),
            )

        self.assertEqual(assessment.status, "restart_required")
        self.assertEqual(
            assessment.detail_code,
            "remote_agentic_attestation_revoked",
        )
        registry.get_agentic_runtime_adapter.assert_not_called()
        provider_store.assert_not_called()

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
