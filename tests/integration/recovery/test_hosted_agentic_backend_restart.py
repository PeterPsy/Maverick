"""Real backend-restart recovery for a committed hosted tool pairing."""

from __future__ import annotations

from dataclasses import replace
import json
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from core.providers.agentic_protocol import EphemeralCredential
from core.providers.maverick_agent_builtins import (
    OPENROUTER_RELACE_GLM_PROVIDER_CONFIG,
)
from core.providers.openrouter_agentic_client import OpenRouterAgenticClient
from core.providers.openrouter_agentic_models import (
    OPENROUTER_AGENTIC_CODEC_ID,
    OPENROUTER_AGENTIC_CODEC_VERSION,
    OPENROUTER_AGENTIC_CONTENT_TYPE,
    OPENROUTER_AGENTIC_MODEL_ID,
    OPENROUTER_AGENTIC_SCHEMA_VERSION,
)
from core.providers.openrouter_agentic_profile import (
    openrouter_agentic_routing_constraint,
)
from core.providers.openrouter_agentic_state import inspect_openrouter_chat_state
from core.providers.service import builtin_provider_registry
from core.recovery import backend_restart
from core.runtime import turn_submission_service_runtime
from core.runtime.execution import execute_runtime_turn
from core.runtime.execution_binding import canonical_digest
from core.runtime.hosted_agentic_models import HostedProviderPrivateCodec
from core.runtime.provider_step_journal import ProviderStepJournal
from tests.support.agentic_runtime import direct_test_provider_store
from tests.support.hosted_agentic_harness import HostedAgenticHarness
from tests.unit.providers.test_openrouter_agentic_codec import (
    _ScriptedTransport,
    _text_stream,
    _tool_stream,
)


OPENROUTER_REQUEST_COST_ESTIMATOR = (
    OPENROUTER_RELACE_GLM_PROVIDER_CONFIG.token_cost_policy.request_ceiling_microusd
)


class HostedAgenticBackendRestartTest(unittest.TestCase):
    def test_backend_restart_transfers_committed_pairing_to_recovery_turn(self) -> None:
        harness = HostedAgenticHarness(
            self,
            model_provider_id="openrouter",
            model_id=OPENROUTER_AGENTIC_MODEL_ID,
            provider_protocol="openrouter-chat-completions",
            routing_constraint=openrouter_agentic_routing_constraint(),
            filesystem_list=True,
        )
        interrupted_transport = _ScriptedTransport([
            _tool_stream(
                "generation-restart-tool",
                harness.filesystem_list_tool_name,
                arguments={"path": ".", "max_depth": 1, "max_results": 10},
            ),
        ])
        interrupted = harness.adapter(
            OpenRouterAgenticClient(transport=interrupted_transport),
            private_codec=HostedProviderPrivateCodec(
                OPENROUTER_AGENTIC_CODEC_ID,
                OPENROUTER_AGENTIC_CODEC_VERSION,
                OPENROUTER_AGENTIC_SCHEMA_VERSION,
                OPENROUTER_AGENTIC_CONTENT_TYPE,
            ),
            credential=EphemeralCredential("fixture-openrouter-key"),
            cost_estimator=OPENROUTER_REQUEST_COST_ESTIMATOR,
            private_state_inspector=inspect_openrouter_chat_state,
        )

        class _BackendRestart(BaseException):
            pass

        def restart_after_tool_commit(point, _record):
            if point == "committed":
                raise _BackendRestart()

        interrupted.loop.provider_step_journal = ProviderStepJournal(
            store=harness.store,
            fault_hook=restart_after_tool_commit,
        )
        interrupted.loop.recovery.journal = interrupted.loop.provider_step_journal
        with self.assertRaises(_BackendRestart):
            execute_runtime_turn(
                session=harness.session,
                provider=harness.provider,
                input_text="Use only synthetic fixture data.",
                agentic_adapter=interrupted,
                provider_state=harness.store.get_provider_state("session-hosted"),
                correlation_id="turn-hosted",
                effective_authority=harness.authority,
            )

        resumed_transport = _ScriptedTransport([
            _text_stream("generation-restart-final", "Recovered after restart"),
        ])

        def authority_for(context):
            authority = replace(
                harness.authority,
                turn_id=context.correlation_id,
                authority_digest="",
            )
            return replace(
                authority,
                authority_digest=canonical_digest(authority),
            )

        resumed = harness.adapter(
            OpenRouterAgenticClient(transport=resumed_transport),
            private_codec=HostedProviderPrivateCodec(
                OPENROUTER_AGENTIC_CODEC_ID,
                OPENROUTER_AGENTIC_CODEC_VERSION,
                OPENROUTER_AGENTIC_SCHEMA_VERSION,
                OPENROUTER_AGENTIC_CONTENT_TYPE,
            ),
            credential=EphemeralCredential("fixture-openrouter-key"),
            cost_estimator=OPENROUTER_REQUEST_COST_ESTIMATOR,
            private_state_inspector=inspect_openrouter_chat_state,
            authority_refresher=authority_for,
            authority_revalidator=lambda context, _authority: authority_for(context),
        )
        registry = builtin_provider_registry()
        registry.register_agentic_runtime_adapter(
            resumed,
            definition=harness.provider,
        )
        state = SimpleNamespace(
            repository_root=harness.root,
            provider_store=direct_test_provider_store(
                harness.binding,
                now=harness.session.updated_at,
            ),
            provider_registry=registry,
            runtime_store=harness.store,
            runtime_event_bus=None,
            runtime_thread_event_bus=None,
            workspace_store=SimpleNamespace(list_workspaces=lambda: []),
        )

        class _ImmediateThread:
            def __init__(self, *, target, name, daemon):
                self.target = target

            def start(self):
                self.target()

        class _DiscardedTimer:
            def __init__(self, _delay, _target):
                self.daemon = False

            def start(self):
                return None

        def recorded_authority(_state, *, turn_id, **_kwargs):
            return authority_for(SimpleNamespace(correlation_id=turn_id))

        def captured_input(_state, *, input_text, **_kwargs):
            return SimpleNamespace(input_text=input_text, sources=())

        with (
            patch.object(backend_restart, "dispatch_source_app_runtime_event"),
            patch.object(backend_restart, "set_thread_availability"),
            patch.object(
                backend_restart,
                "dispatch_workspace_app_background_hooks",
                return_value=[],
            ),
            patch.object(turn_submission_service_runtime, "Thread", _ImmediateThread),
            patch.object(turn_submission_service_runtime, "Timer", _DiscardedTimer),
            patch.object(
                turn_submission_service_runtime,
                "resolve_runtime_engine_for_session",
                return_value=(harness.provider, None, resumed, None),
            ),
            patch.object(
                turn_submission_service_runtime,
                "preflight_runtime_context_capabilities",
            ),
            patch.object(
                turn_submission_service_runtime,
                "resolve_and_record_runtime_authority",
                side_effect=recorded_authority,
            ),
            patch(
                "core.runtime.resolved_runtime_engine.resolve_and_record_runtime_authority",
                side_effect=recorded_authority,
            ),
            patch.object(
                turn_submission_service_runtime,
                "capture_runtime_provider_input",
                side_effect=captured_input,
            ),
            patch.object(
                turn_submission_service_runtime,
                "release_idle_runtime_processes",
                return_value=0,
            ),
            patch(
                "core.runtime.turn_submission_service_queue.schedule_runtime_thread_title_generation"
            ),
            patch(
                "core.runtime.turn_queue_admission.remote_agentic_containment_reason",
                return_value=None,
            ),
            patch(
                "core.recovery.continuation_admission.require_remote_agentic_authority",
                return_value=None,
            ),
            patch(
                "core.runtime.provider_start_handoff.require_remote_agentic_dispatch",
                return_value=None,
            ),
        ):
            recovery = (
                backend_restart.recover_interrupted_runtime_turns_after_backend_restart(
                    state
                )
            )

        recovery_turn = next(
            turn
            for turn in harness.store.list_turns(harness.session.session_id)
            if turn.turn_id != "turn-hosted"
        )
        self.assertEqual(recovery.queued_resume_turns, 1)
        self.assertEqual(harness.store.get_turn("turn-hosted").status, "failed")
        self.assertEqual(
            recovery_turn.status,
            "completed",
            msg=recovery_turn.failure_reason,
        )
        self.assertEqual(
            recovery_turn.provider_pairing_source_turn_id,
            "turn-hosted",
        )
        self.assertEqual(
            len(
                harness.store.list_tool_invocations(
                    session_id="session-hosted"
                )
            ),
            1,
        )
        self.assertIn(
            harness.filesystem_marker,
            json.dumps(resumed_transport.payloads[0]),
        )
        final_event = next(
            event
            for event in harness.store.list_events(harness.session.session_id)
            if event.turn_id == recovery_turn.turn_id
            and event.event_type == "runtime.output.final"
        )
        self.assertEqual(
            final_event.payload["complete_text"],
            "Recovered after restart",
        )



if __name__ == "__main__":
    unittest.main()
