"""Provider status reads must reuse the process-owned native catalog fence."""

from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from core.api.provider_api import workspace_provider_status
from core.api.app_mounts import handle_app_backend


class ProviderStatusRegistryTest(unittest.TestCase):
    def test_app_backend_metadata_reuses_platform_registry(self) -> None:
        store = object()
        registry = object()
        workspace_store = object()
        state = SimpleNamespace(provider_store=store, provider_registry=registry, workspace_store=workspace_store)
        binding = SimpleNamespace(source_kind="platform", data_root=Path("/unused"))
        parsed = SimpleNamespace(app_id="chat", contract=SimpleNamespace(
            entrypoints=SimpleNamespace(backend=object()),
        ))
        with (
            patch(
                "core.api.app_mounts.resolve_app_surface",
                return_value=(binding, Path("/unused"), parsed),
            ),
            patch("core.api.app_mounts._read_backend_body", return_value=({}, None)),
            patch(
                "core.api.app_mounts.resolve_provider_for_workspace",
                side_effect=RuntimeError("provider lookup reached"),
            ) as resolve,
            self.assertRaisesRegex(RuntimeError, "provider lookup reached"),
        ):
            handle_app_backend(
                state, environ={"REQUEST_METHOD": "POST"}, workspace_id="workspace-one",
                app_id="chat", user=None, start_path=Path("/unused"),
                start_response=lambda *_args: None, trusted_platform_invocation=True,
            )

        resolve.assert_called_once_with(store, workspace_id="workspace-one", registry=registry, workspace_store=workspace_store)

    def test_status_resolution_reuses_platform_registry_even_on_explicit_refresh(self) -> None:
        for refresh in (False, True):
            with self.subTest(refresh=refresh):
                store = SimpleNamespace()
                registry = object()
                workspace_store = object()
                state = SimpleNamespace(provider_store=store, provider_registry=registry, workspace_store=workspace_store)
                status = SimpleNamespace(
                    active_provider=None,
                    selection=None,
                    configured=False,
                    blocked_reason="no_provider_configured",
                    blocked_detail=None,
                    available_providers=[],
                )
                with (
                    patch("core.api.provider_api.resolve_workspace_provider_status", return_value=status) as resolve,
                    patch("core.api.provider_api.effective_provider_registry", return_value=registry),
                    patch("core.api.provider_api.native_agent_status_items", return_value=[]),
                    patch("core.api.provider_api.workspace_agentic_profile_status", return_value={"items": []}),
                    patch("core.api.provider_api.workspace_hosted_text_status", return_value={}),
                    patch("core.api.provider_api.workspace_speech_stt_status", return_value={}),
                ):
                    payload = workspace_provider_status(
                        state, workspace_id="workspace-one", refresh_model_catalog=refresh,
                    )

                resolve.assert_called_once_with(
                    store, workspace_id="workspace-one", registry=registry,
                    refresh_model_catalog=refresh, workspace_store=workspace_store,
                )
                self.assertFalse(payload["configured"])
                self.assertEqual(payload["blocked_reason"], "no_provider_configured")


if __name__ == "__main__":
    unittest.main()
