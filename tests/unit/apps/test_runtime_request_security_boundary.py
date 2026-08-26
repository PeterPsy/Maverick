from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import core.apps.runtime_requests as runtime_requests
from core.apps.errors import AppHostingError


class RuntimeRequestSecurityBoundaryTest(unittest.TestCase):
    def test_app_request_envelopes_never_silently_drop_non_objects(self) -> None:
        parsed = SimpleNamespace(
            contract=SimpleNamespace(
                permissions=SimpleNamespace(
                    runtime=SimpleNamespace(create_sessions=True)
                ),
                capabilities=SimpleNamespace(data_events=[]),
            )
        )
        for field_name in (
            "runtime_session_requests",
            "runtime_turn_interrupt_requests",
            "dependency_backend_requests",
        ):
            with self.subTest(field_name=field_name):
                result = {field_name: ["unsupported-string-entry"]}
                with self.assertRaises(AppHostingError):
                    runtime_requests.apply_app_runtime_requests(
                        SimpleNamespace(),
                        result=result,
                        workspace_id="default",
                        app_id="fixture",
                        source_root=Path("/apps/fixture"),
                        backend_entrypoint=None,
                        data_root="workspaces/default/data/fixture",
                        parsed=parsed,
                        start_path=Path(__file__).resolve().parents[3],
                    )

    def test_app_runtime_request_pins_authorized_agentic_profile_before_publish(self) -> None:
        governance = SimpleNamespace(allow_full_access_runtime=False)
        registry = object()
        definition = object()
        workspace_binding = SimpleNamespace(binding_id="binding-codex", revision=3)
        routing = SimpleNamespace(effective_mode="sandbox")
        created = SimpleNamespace(
            session_id="runtime-app-session",
            system_prompt="bounded app prompt",
            started_at=datetime(2026, 8, 25, tzinfo=UTC),
            updated_at=datetime(2026, 8, 25, tzinfo=UTC),
        )
        state = SimpleNamespace(
            runtime_store=object(),
            provider_store=object(),
            provider_registry=registry,
            app_store=object(),
            observability_store=None,
            workspace_store=SimpleNamespace(
                get_governance=lambda _workspace_id: governance
            ),
        )
        request = {
            "agent_id": "chat",
            "agent_type_id": "chat",
            "requested_mode": "sandbox",
        }
        with (
            patch.object(runtime_requests, "_materialized_system_prompt", return_value="bounded app prompt"),
            patch.object(runtime_requests, "build_runtime_routing", return_value=routing),
            patch.object(runtime_requests, "resolve_runtime_execution_mode", return_value="sandbox"),
            patch.object(runtime_requests, "effective_provider_registry", return_value=registry),
            patch.object(
                runtime_requests,
                "_authorize_new_agentic_app_session",
                return_value=(definition, workspace_binding),
            ),
            patch.object(
                runtime_requests,
                "build_pinned_execution_binding",
                side_effect=lambda *_args, **kwargs: SimpleNamespace(
                    session_id=kwargs["session_id"],
                    workspace_id=kwargs["workspace_id"],
                    execution_mode=kwargs["execution_mode"],
                    workspace_binding_id="binding-codex",
                    workspace_binding_revision=3,
                ),
            ) as pin,
            patch.object(
                runtime_requests,
                "preflight_execution_binding_context",
                return_value=None,
            ),
            patch.object(runtime_requests, "runtime_skill_catalog_app_id_for_request", return_value=None),
            patch.object(runtime_requests, "create_runtime_session", return_value=created) as create_session,
            patch.object(runtime_requests, "transition_runtime_session", return_value=created),
            patch.object(runtime_requests, "create_runtime_thread"),
        ):
            preflight = runtime_requests._preflight_runtime_request_before_persistence(
                state, request=request, workspace_id="default",
                app_id="design-studio", actor_user_id="user:admin",
            )
            observed = runtime_requests._runtime_session_for_request(
                state, request=request, workspace_id="default",
                app_id="design-studio", parsed=SimpleNamespace(),
                start_path=Path("/repo"), actor_user_id="user:admin",
                preflight=preflight,
            )
        self.assertIs(observed, created)
        self.assertIs(pin.call_args.kwargs["authorized_definition_snapshot"], definition)
        self.assertIs(pin.call_args.kwargs["authorized_workspace_binding_snapshot"], workspace_binding)
        self.assertIs(create_session.call_args.kwargs["execution_binding"], preflight.execution_binding)
        self.assertEqual(preflight.execution_binding.session_id, pin.call_args.kwargs["session_id"])
        self.assertIs(create_session.call_args.kwargs["routing"], routing)
        self.assertIsNone(create_session.call_args.kwargs["declared_remote_data_class"])


if __name__ == "__main__":
    unittest.main()
