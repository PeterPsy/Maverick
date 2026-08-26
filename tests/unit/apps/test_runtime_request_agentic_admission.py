from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import core.apps.runtime_requests as runtime_requests
from core.providers.errors import ProviderError
from core.runtime.agentic_feature_flags import (
    MAVERICK_FEATURE_GOOGLE_AGENTIC_PREVIEW,
    MAVERICK_FEATURE_HOSTED_AGENT_RUNTIME,
)


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
