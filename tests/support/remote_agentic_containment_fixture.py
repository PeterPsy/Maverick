"""Reusable fixture for remote-agentic containment contract tests."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

from core.providers.maverick_agent_builtins import HOSTED_TOOL_LOOP_ADAPTER_VERSION
from core.providers.agentic_models import WorkspaceAgenticProfileBinding, default_actor_selection_policy
from core.providers.agentic_profiles import publish_codex_agentic_profile
from core.providers.google_agentic_profile import ensure_google_agentic_preview_profile
from core.providers.service import builtin_provider_registry, register_builtin_providers
from core.providers.store import ProviderCollections, ProviderDocumentStore
from core.runtime.execution_binding import build_runtime_execution_binding
from core.runtime.provider_state import RuntimeProviderState
from core.runtime.runtime_events import RuntimeEventRecord
from core.runtime.runtime_session import RuntimeSessionRecord
from core.runtime.runtime_state import RuntimeStateRecord
from core.runtime.runtime_turns import RuntimeTurnRecord
from core.runtime.store import RuntimeCollections, RuntimeDocumentStore
from core.runtime.tool_models import ToolInvocationRecord
from tests.support.collections import FakeCollection


NOW = datetime(2026, 8, 25, 18, 0, tzinfo=UTC)


class RemoteAgenticContainmentFixture:
    """Build Codex and contained-remote state without defining test cases."""

    def setUp(self) -> None:
        self.provider_store = ProviderDocumentStore(
            ProviderCollections(
                definitions=FakeCollection(),
                bindings=FakeCollection(),
                selections=FakeCollection(),
                agentic_profile_definitions=FakeCollection(),
                workspace_agentic_profile_bindings=FakeCollection(),
            )
        )
        self.runtime_store = RuntimeDocumentStore(
            RuntimeCollections(
                sessions=FakeCollection(),
                turns=FakeCollection(),
                events=FakeCollection(),
                processes=FakeCollection(),
                states=FakeCollection(),
                threads=FakeCollection(),
                provider_states=FakeCollection(),
                tool_invocations=FakeCollection(),
            )
        )
        self.registry = builtin_provider_registry(refresh_model_catalog=False)
        register_builtin_providers(self.provider_store, registry=self.registry)
        codex_definition = publish_codex_agentic_profile(
            self.provider_store,
            definition=self.registry.get_provider_definition("codex"),
            model_id="gpt-5.6-sol",
            now=NOW,
        )
        self.codex_binding = self.provider_store.save_workspace_agentic_profile_binding(
            WorkspaceAgenticProfileBinding(
                binding_id="binding-codex-enabled",
                workspace_id="default",
                definition_id=codex_definition.definition_id,
                credential_binding_id=None,
                enabled=True,
                is_default=True,
                actor_policy=default_actor_selection_policy(),
                workspace_policy_ceiling=codex_definition.policy_ceiling,
                egress_policy_id=codex_definition.egress_policy_id,
                egress_policy_revision=codex_definition.egress_policy_revision,
                created_at=NOW,
                updated_at=NOW,
            ),
        )
        self.remote_definition = ensure_google_agentic_preview_profile(
            self.provider_store,
            adapter=SimpleNamespace(
                runtime_engine_id="maverick-tool-loop",
                adapter_id="maverick-hosted-tool-loop",
                adapter_version=HOSTED_TOOL_LOOP_ADAPTER_VERSION,
            ),
            now=NOW,
        )
        self.remote_binding = self.provider_store.save_workspace_agentic_profile_binding(
            WorkspaceAgenticProfileBinding(
                binding_id="binding-google-enabled",
                workspace_id="default",
                definition_id=self.remote_definition.definition_id,
                credential_binding_id="credential-redacted-from-report",
                enabled=True,
                is_default=False,
                actor_policy=default_actor_selection_policy(),
                workspace_policy_ceiling=self.remote_definition.policy_ceiling,
                egress_policy_id=self.remote_definition.egress_policy_id,
                egress_policy_revision=self.remote_definition.egress_policy_revision,
                created_at=NOW,
                updated_at=NOW,
            ),
        )
        self.remote_session = self._save_remote_mismatch_session()

    def _save_remote_mismatch_session(self) -> RuntimeSessionRecord:
        binding = build_runtime_execution_binding(
            session_id="session-google-ambiguous",
            workspace_id="default",
            workspace_binding_id=self.remote_binding.binding_id,
            runtime_engine_id=self.remote_definition.runtime_engine_id,
            adapter_id=self.remote_definition.adapter_id,
            adapter_version="5",
            model_provider_id=self.remote_definition.model_provider_id,
            model_id=self.remote_definition.model_id,
            provider_protocol=self.remote_definition.provider_protocol,
            provider_api_version=self.remote_definition.provider_api_version,
            routing_constraint=self.remote_definition.routing_constraint,
            credential_binding_id=None,
            reasoning_effort="high",
            reasoning_efforts=("high",),
            capabilities=self.remote_definition.capabilities,
            execution_mode="sandbox",
            runtime_policy=self.remote_definition.policy_ceiling,
            egress_policy_id=self.remote_definition.egress_policy_id,
            egress_policy_revision=self.remote_definition.egress_policy_revision,
            created_at=NOW,
        )
        session = RuntimeSessionRecord(
            session_id=binding.session_id,
            workspace_id=binding.workspace_id,
            agent_id="chat",
            status="running",
            requested_mode="sandbox",
            effective_mode="sandbox",
            workspace_root="/workspace",
            workdir="/workspace",
            runtime_root="/runtime/session-google-ambiguous",
            started_at=NOW,
            updated_at=NOW,
            ended_at=None,
            last_progress_at=NOW,
            execution_binding=binding,
            provider_id=binding.runtime_engine_id,
        )
        self.runtime_store.insert_session(session)
        self.runtime_store.save_state(
            RuntimeStateRecord(
                session_id=session.session_id,
                workspace_id=session.workspace_id,
                current_turn_id="turn-google-ambiguous",
                session_status="running",
                turn_status="failed",
                last_progress_at=NOW,
                watchdog_deadline_at=None,
                forced_stop_reason=None,
                last_error_detail=None,
                updated_at=NOW,
            )
        )
        self.runtime_store.initialize_provider_state(
            RuntimeProviderState(
                session_id=session.session_id,
                workspace_id=session.workspace_id,
                runtime_engine_id=binding.runtime_engine_id,
                model_provider_id=binding.model_provider_id,
                continuation_id=None,
                provider_thread_id=None,
                provider_request_id="request-5",
                provider_private_envelope=None,
                revision=0,
                turn_generation="turn-google-ambiguous",
                updated_at=NOW,
            )
        )
        self.runtime_store.save_turn(
            RuntimeTurnRecord(
                turn_id="turn-google-ambiguous",
                session_id=session.session_id,
                workspace_id=session.workspace_id,
                status="failed",
                input_text="redacted",
                created_at=NOW,
                updated_at=NOW,
                started_at=NOW,
                completed_at=NOW,
                failure_reason="agent_step_limit_reached",
            )
        )
        for index in range(1, 5):
            invocation_time = NOW + timedelta(seconds=index * 10 + 2)
            saved = self.runtime_store.initialize_tool_invocation(
                ToolInvocationRecord(
                    invocation_id=f"invocation-{index}",
                    workspace_id=session.workspace_id,
                    session_id=session.session_id,
                    turn_id="turn-google-ambiguous",
                    provider_tool_call_id=f"provider-call-{index}",
                    resolved_tool_handle="core-capability:filesystem.read",
                    arguments_private_ref=f"private:arguments:{index}",
                    arguments_summary={"field_count": 1},
                    arguments_digest=f"{index}" * 64,
                    idempotency_key=f"{index + 4}" * 64,
                    effect_class="read",
                    state="proposed",
                    policy_revision="1",
                    authority_digest="f" * 64,
                    confirmation_grant_id=None,
                    result_private_ref=None,
                    result_summary=None,
                    failure_reason=None,
                    revision=0,
                    created_at=invocation_time,
                    updated_at=invocation_time,
                )
            )
            if index == 4:
                self.runtime_store.update_tool_invocation(
                    replace(
                        saved,
                        state="execution_unknown",
                        failure_reason="runtime_restart_execution_ambiguous",
                        revision=1,
                    ),
                    expected_revision=0,
                )
        for index in range(1, 6):
            step_time = NOW + timedelta(seconds=index * 10)
            self.runtime_store.save_event(
                RuntimeEventRecord(
                    event_id=f"request-{index}",
                    workspace_id=session.workspace_id,
                    session_id=session.session_id,
                    plane="turn",
                    event_type="runtime.provider.turn_start_sent",
                    turn_id="turn-google-ambiguous",
                    process_id=None,
                    payload={"request_id": f"request-{index}"},
                    created_at=step_time,
                )
            )
            self.runtime_store.save_event(
                RuntimeEventRecord(
                    event_id=f"acceptance-{index}",
                    workspace_id=session.workspace_id,
                    session_id=session.session_id,
                    plane="turn",
                    event_type="runtime.provider.accepted",
                    turn_id="turn-google-ambiguous",
                    process_id=None,
                    payload={"request_id": f"request-{index}"},
                    created_at=step_time + timedelta(seconds=1),
                )
            )
            outcome_type = "runtime.tool_call.proposed" if index < 5 else "runtime.output.final"
            outcome_payload = (
                {"invocation_id": f"invocation-{index}"}
                if index < 5
                else {"text": "bounded final"}
            )
            self.runtime_store.save_event(
                RuntimeEventRecord(
                    event_id=f"outcome-{index}",
                    workspace_id=session.workspace_id,
                    session_id=session.session_id,
                    plane="turn",
                    event_type=outcome_type,
                    turn_id="turn-google-ambiguous",
                    process_id=None,
                    payload=outcome_payload,
                    created_at=step_time + timedelta(seconds=3),
                )
            )
        return session

    def _codex_snapshot(self):
        return (
            self.provider_store.get_workspace_agentic_profile_binding(self.codex_binding.binding_id),
            self.provider_store.get_agentic_profile_definition(self.codex_binding.definition_id),
        )

    def _state_snapshot(self):
        return (
            self.provider_store.get_workspace_agentic_profile_binding(self.remote_binding.binding_id),
            self.provider_store.get_agentic_profile_definition(self.remote_definition.definition_id),
            self.runtime_store.get_session(self.remote_session.session_id),
            self.runtime_store.get_state(self.remote_session.session_id),
        )
