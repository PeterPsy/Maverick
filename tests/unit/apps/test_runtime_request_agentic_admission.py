from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
import os
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import core.apps.runtime_requests as runtime_requests
from core.api.platform_state import bootstrap_platform_state
from core.providers.agentic_profiles import resolve_workspace_agentic_profile
from core.providers.errors import ProviderError
from core.providers.errors import CapabilityCertificateError
from core.runtime.agentic_feature_flags import (
    MAVERICK_FEATURE_GOOGLE_AGENTIC_PREVIEW,
    MAVERICK_FEATURE_HOSTED_AGENT_RUNTIME,
)
from tests.support.repo import make_temp_repo_root


class RuntimeRequestAgenticAdmissionTest(unittest.TestCase):
    def setUp(self) -> None:
        self.definition = SimpleNamespace(
            runtime_engine_id="maverick-tool-loop",
            model_provider_id="google-ai-studio",
            provider_protocol="google-interactions",
        )
        self.binding = SimpleNamespace(binding_id="binding-google-contained", revision=4)
        self.runtime_store = Mock()
        self.state = SimpleNamespace(
            provider_store=object(),
            runtime_store=self.runtime_store,
            repository_root=Path("/repo"),
            observability_store=None,
        )
        self.environment = {
            MAVERICK_FEATURE_HOSTED_AGENT_RUNTIME: "1",
            MAVERICK_FEATURE_GOOGLE_AGENTIC_PREVIEW: "1",
        }

    def test_remote_app_request_and_fake_declaration_fail_before_store_use(self) -> None:
        for declaration in (None, "workspace_internal_fake"):
            request = {
                "agent_id": "chat",
                "runtime_mode": "agentic",
                "workspace_profile_binding_id": self.binding.binding_id,
                **(
                    {"declared_remote_data_class": declaration}
                    if declaration is not None
                    else {}
                ),
            }
            with self.subTest(declaration=declaration), self._authorized_remote_profile(), patch.dict(
                "os.environ", self.environment, clear=True
            ):
                expected = (
                    "remote_data_declaration_not_accepted"
                    if declaration is not None
                    else "remote_agentic_attestation_unavailable"
                )
                with self.assertRaisesRegex(ProviderError, expected):
                    runtime_requests._preflight_runtime_request_before_persistence(
                        self.state,
                        request=request,
                        workspace_id="default",
                        app_id="sensor-hub",
                        actor_user_id="user:admin",
                    )
            self.assertEqual(self.runtime_store.method_calls, [])

    def test_app_cannot_submit_policy_or_classification_authority(self) -> None:
        for authority_fields in (
            {"data_class": "workspace_internal_fake"},
            {"egress_policy_id": "browser-policy"},
            {"attestation_revision": 99},
        ):
            with self.subTest(authority_fields=authority_fields), self.assertRaisesRegex(
                CapabilityCertificateError,
                "runtime_client_authority_not_accepted",
            ):
                runtime_requests._preflight_runtime_request_before_persistence(
                    self.state,
                    request={
                        "agent_id": "chat",
                        "runtime_mode": "agentic",
                        **authority_fields,
                    },
                    workspace_id="default",
                    app_id="sensor-hub",
                    actor_user_id="user:admin",
                )
        self.assertEqual(self.runtime_store.method_calls, [])

    def test_unsupported_context_fails_before_app_session_or_stream_persistence(self) -> None:
        state = SimpleNamespace(
            provider_store=object(),
            provider_registry=object(),
            runtime_store=Mock(),
            workspace_store=SimpleNamespace(get_governance=lambda _workspace_id: object()),
        )
        definition = object()
        binding = SimpleNamespace(binding_id="binding-codex", revision=2)
        execution_binding = SimpleNamespace(
            runtime_engine_id="codex",
            workspace_binding_id="binding-codex",
            workspace_binding_revision=2,
        )
        registry = SimpleNamespace(get_agentic_runtime_adapter=lambda _engine_id: object())
        with patch.object(
            runtime_requests,
            "_authorize_new_agentic_app_session",
            return_value=(definition, binding),
        ), patch.object(
            runtime_requests,
            "effective_provider_registry",
            return_value=registry,
        ), patch.object(
            runtime_requests,
            "resolve_runtime_execution_mode",
            return_value="sandbox",
        ), patch.object(
            runtime_requests,
            "build_pinned_execution_binding",
            return_value=execution_binding,
        ), patch.object(
            runtime_requests,
            "preflight_execution_binding_context",
            side_effect=CapabilityCertificateError(
                "agentic_app_references_not_effective"
            ),
        ) as capability_preflight:
            with self.assertRaisesRegex(
                CapabilityCertificateError,
                "agentic_app_references_not_effective",
            ):
                runtime_requests._preflight_runtime_request_before_persistence(
                    state,
                    request={
                        "agent_id": "chat",
                        "runtime_mode": "agentic",
                        "app_references": [{"app_id": "crm"}],
                    },
                    workspace_id="default",
                    app_id="sensor-hub",
                    actor_user_id="user:admin",
                )

        capability_preflight.assert_called_once()
        self.assertEqual(state.runtime_store.method_calls, [])

    def test_remote_stream_request_is_rejected_before_reservation(self) -> None:
        request = {
            "request_id": "remote-stream",
            "idempotency_key": "remote-stream-key",
            "create_stream": True,
            "agent_id": "chat",
            "runtime_mode": "agentic",
            "workspace_profile_binding_id": self.binding.binding_id,
            "input_text": "must not persist",
        }
        with self._authorized_remote_profile(), patch.dict(
            "os.environ", self.environment, clear=True
        ), patch.object(
            runtime_requests, "_record_runtime_request_failed"
        ), patch.object(
            runtime_requests,
            "_invoke_runtime_request_callback",
            return_value={"status_code": 0},
        ):
            result = runtime_requests._apply_one_runtime_request(
                self.state,
                request=request,
                workspace_id="default",
                app_id="sensor-hub",
                source_root=Path("/apps/sensor-hub"),
                backend_entrypoint=None,
                data_root="workspaces/default/data/sensor-hub",
                parsed=SimpleNamespace(),
                start_path=Path("/repo"),
                actor_user_id="user:admin",
            )

        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["error"], "remote_agentic_attestation_unavailable")
        self.runtime_store.reserve_app_stream.assert_not_called()

    def test_profile_mutation_fails_before_app_stream_or_runtime_records(self) -> None:
        for mutation in ("revision", "default", "definition"):
            with self.subTest(mutation=mutation):
                root = make_temp_repo_root(self)
                with patch.dict(
                    os.environ,
                    {"MAVERICK_ALLOW_INSECURE_TEST_DEFAULTS": "1"},
                    clear=False,
                ):
                    state = bootstrap_platform_state(
                        start_path=root,
                        install_builtin_apps=False,
                    )
                resolver = self._mutating_profile_resolver(
                    state,
                    mutation=mutation,
                )
                before_sessions = state.runtime_store.list_all_sessions()
                before_threads = state.runtime_store.list_threads("default")
                with patch.object(
                    runtime_requests,
                    "resolve_workspace_agentic_profile",
                    side_effect=resolver,
                ), patch.object(
                    runtime_requests,
                    "resolve_runtime_actor_roles",
                    return_value=("admin", "user:admin", "admin"),
                ), patch.object(
                    runtime_requests,
                    "actor_selection_allowed",
                    return_value=True,
                ), patch.object(
                    state.runtime_store,
                    "reserve_app_stream",
                    wraps=state.runtime_store.reserve_app_stream,
                ) as reserve_app_stream, patch.object(
                    runtime_requests,
                    "create_runtime_session",
                ) as create_session, patch.object(
                    runtime_requests,
                    "create_runtime_thread",
                ) as create_thread, patch.object(
                    runtime_requests,
                    "submit_runtime_turn_async",
                ) as submit_turn, patch.object(
                    runtime_requests,
                    "_record_runtime_request_failed",
                ), patch.object(
                    runtime_requests,
                    "_invoke_runtime_request_callback",
                    return_value={"status_code": 0},
                ):
                    result = runtime_requests._apply_one_runtime_request(
                        state,
                        request={
                            "request_id": f"mutating-{mutation}",
                            "idempotency_key": f"mutating-{mutation}",
                            "create_stream": True,
                            "agent_id": "chat",
                            "runtime_mode": "agentic",
                            "input_text": "must not persist",
                        },
                        workspace_id="default",
                        app_id="sensor-hub",
                        source_root=root / "apps" / "sensor-hub",
                        backend_entrypoint=None,
                        data_root="workspaces/default/data/sensor-hub",
                        parsed=SimpleNamespace(),
                        start_path=root,
                        actor_user_id="user:admin",
                    )

                self.assertEqual(result["status"], "failed")
                self.assertIn(
                    result["error"],
                    {
                        "workspace_profile_binding_changed",
                        "profile_definition_invalid",
                    },
                )
                reserve_app_stream.assert_not_called()
                create_session.assert_not_called()
                create_thread.assert_not_called()
                submit_turn.assert_not_called()
                self.assertEqual(
                    state.runtime_store.list_all_sessions(),
                    before_sessions,
                )
                self.assertEqual(
                    state.runtime_store.list_threads("default"),
                    before_threads,
                )

    def _authorized_remote_profile(self):
        return _PatchGroup(
            patch.object(
                runtime_requests,
                "resolve_workspace_agentic_profile",
                return_value=(self.definition, self.binding),
            ),
            patch.object(
                runtime_requests,
                "resolve_runtime_actor_roles",
                return_value=("admin", "user:admin", "admin"),
            ),
            patch.object(runtime_requests, "actor_selection_allowed", return_value=True),
        )

    @staticmethod
    def _mutating_profile_resolver(state, *, mutation: str):
        def resolve_then_mutate(*args, **kwargs):
            definition, binding = resolve_workspace_agentic_profile(*args, **kwargs)
            now = datetime.now(UTC)
            if mutation == "revision":
                state.provider_store.save_workspace_agentic_profile_binding(
                    replace(
                        binding,
                        revision=binding.revision + 1,
                        updated_at=now,
                    ),
                    expected_revision=binding.revision,
                )
            elif mutation == "default":
                state.provider_store.save_workspace_agentic_profile_binding(
                    replace(
                        binding,
                        is_default=False,
                        revision=binding.revision + 1,
                        updated_at=now,
                    ),
                    expected_revision=binding.revision,
                )
                state.provider_store.save_workspace_agentic_profile_binding(
                    replace(
                        binding,
                        binding_id="workspace-agentic-concurrent-app-default",
                        revision=0,
                        created_at=now,
                        updated_at=now,
                    ),
                    expected_revision=None,
                )
            elif mutation == "definition":
                status = state.provider_store.get_agentic_profile_definition_status(
                    definition.definition_id,
                    definition.revision,
                )
                state.provider_store.save_agentic_profile_definition_status(
                    replace(
                        status,
                        rollout_status="suspended",
                        revision=status.revision + 1,
                        updated_at=now,
                    ),
                    expected_revision=status.revision,
                )
            else:
                raise AssertionError(f"Unknown mutation {mutation}")
            return definition, binding

        return resolve_then_mutate


class _PatchGroup:
    def __init__(self, *patchers) -> None:
        self.patchers = patchers

    def __enter__(self):
        for patcher in self.patchers:
            patcher.start()
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        for patcher in reversed(self.patchers):
            patcher.stop()


if __name__ == "__main__":
    unittest.main()
