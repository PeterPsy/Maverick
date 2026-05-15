"""Tests for Maverick CLI wrapper bootstrap selection."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from core.app_sdk.cli import _bootstrap_options_for_cli, _bootstrap_state_for_cli


NO_RUNTIME_ENV = {
    "MAVERICK_RUNTIME_API_TOKEN": "",
    "MAVERICK_RUNTIME_ROOT": "",
    "MAVERICK_RUNTIME_SESSION_ID": "",
}


class _FakeAppStore:
    def __init__(
        self,
        *,
        sources: list[object] | None = None,
        bindings: list[object] | None = None,
        bindings_by_workspace: dict[str, list[object]] | None = None,
    ) -> None:
        self._sources = list(sources or [])
        self._bindings = list(bindings or [])
        self._bindings_by_workspace = {
            key: list(value)
            for key, value in (bindings_by_workspace or {}).items()
        }

    def list_app_sources(self) -> list[object]:
        return list(self._sources)

    def list_workspace_app_bindings(self, workspace_id: str) -> list[object]:
        return list(self._bindings_by_workspace.get(workspace_id, self._bindings))


def _state(
    *,
    sources: list[object] | None = None,
    bindings: list[object] | None = None,
    bindings_by_workspace: dict[str, list[object]] | None = None,
):
    return SimpleNamespace(
        repository_root=Path("/repo"),
        app_store=_FakeAppStore(
            sources=sources,
            bindings=bindings,
            bindings_by_workspace=bindings_by_workspace,
        ),
    )


class CliBootstrapTests(unittest.TestCase):
    def test_read_only_discovery_commands_use_sidecar_bootstrap(self) -> None:
        expected = {
            "install_builtin_apps": False,
            "register_builtin_provider_definitions": False,
            "bootstrap_admin": False,
        }

        self.assertEqual(_bootstrap_options_for_cli(["apps", "list", "--json"]), expected)
        self.assertEqual(_bootstrap_options_for_cli(["core", "cli", "list", "--json"]), expected)
        self.assertEqual(_bootstrap_options_for_cli(["core", "mcp", "inspect", "developer-context.read", "--json"]), expected)
        self.assertEqual(
            _bootstrap_options_for_cli(["core", "cli", "run", "developer-context.read", "--doc-id", "AGENTS.md", "--json"]),
            expected,
        )
        self.assertEqual(_bootstrap_options_for_cli(["app", "agents", "mcp", "list", "--json"]), expected)
        self.assertEqual(_bootstrap_options_for_cli(["sdk", "docs", "--json"]), expected)

    def test_mutating_commands_keep_full_bootstrap(self) -> None:
        self.assertEqual(_bootstrap_options_for_cli(["core", "cli", "run", "core.app-sdk.create", "--json"]), {})
        self.assertEqual(_bootstrap_options_for_cli(["app", "agents", "cli", "run", "create", "--json"]), {})
        self.assertEqual(_bootstrap_options_for_cli(["app", "agents", "frontend", "build", "--json"]), {})

    def test_sidecar_app_discovery_retries_host_bootstrap_when_app_state_is_empty(self) -> None:
        light_state = _state()
        full_state = _state(sources=[object()], bindings=[SimpleNamespace(status="enabled")])

        with patch.dict(
            os.environ,
            NO_RUNTIME_ENV,
            clear=False,
        ):
            with patch(
                "core.app_sdk.cli.bootstrap_platform_state",
                side_effect=[light_state, full_state],
            ) as bootstrap:
                state = _bootstrap_state_for_cli(
                    ["apps", "list", "--json"],
                    repository_root=Path("/repo"),
                )

        self.assertIs(state, full_state)
        self.assertEqual(bootstrap.call_count, 2)
        self.assertEqual(
            bootstrap.call_args_list[0].kwargs,
            {
                "start_path": Path("/repo"),
                "install_builtin_apps": False,
                "register_builtin_provider_definitions": False,
                "bootstrap_admin": False,
            },
        )
        self.assertEqual(bootstrap.call_args_list[1].kwargs, {"start_path": Path("/repo"), "bootstrap_admin": False})

    def test_sidecar_app_discovery_retries_for_requested_workspace_without_bindings(self) -> None:
        enabled_binding = SimpleNamespace(status="enabled")
        light_state = _state(
            sources=[object()],
            bindings_by_workspace={"default": [enabled_binding], "acme": []},
        )
        full_state = _state(
            sources=[object()],
            bindings_by_workspace={"default": [enabled_binding], "acme": [enabled_binding]},
        )

        with patch.dict(
            os.environ,
            NO_RUNTIME_ENV,
            clear=False,
        ):
            with patch(
                "core.app_sdk.cli.bootstrap_platform_state",
                side_effect=[light_state, full_state],
            ):
                state = _bootstrap_state_for_cli(
                    ["apps", "list", "--workspace", "acme", "--json"],
                    repository_root=Path("/repo"),
                )

        self.assertIs(state, full_state)

    def test_stale_runtime_session_id_does_not_suppress_host_bootstrap_retry(self) -> None:
        light_state = _state()
        full_state = _state(sources=[object()], bindings=[SimpleNamespace(status="enabled")])

        with patch.dict(
            os.environ,
            {
                **NO_RUNTIME_ENV,
                "MAVERICK_RUNTIME_SESSION_ID": "stale-session",
            },
            clear=False,
        ):
            with patch(
                "core.app_sdk.cli.bootstrap_platform_state",
                side_effect=[light_state, full_state],
            ) as bootstrap:
                state = _bootstrap_state_for_cli(
                    ["apps", "list", "--json"],
                    repository_root=Path("/repo"),
                )

        self.assertIs(state, full_state)
        self.assertEqual(bootstrap.call_count, 2)

    def test_runtime_sidecar_discovery_does_not_retry_host_bootstrap(self) -> None:
        light_state = _state()

        with tempfile.TemporaryDirectory() as temp:
            runtime_root = Path(temp)
            shim = runtime_root / "bin" / "maverick"
            shim.parent.mkdir(parents=True)
            shim.write_text("#!/bin/sh\n", encoding="utf-8")
            shim.chmod(0o755)

            with patch.dict(
                os.environ,
                {
                    "MAVERICK_RUNTIME_API_TOKEN": "token",
                    "MAVERICK_RUNTIME_ROOT": str(runtime_root),
                    "MAVERICK_RUNTIME_SESSION_ID": "sess-1",
                },
                clear=False,
            ):
                with patch("core.app_sdk.cli.bootstrap_platform_state", return_value=light_state) as bootstrap:
                    state = _bootstrap_state_for_cli(
                        ["apps", "list", "--json"],
                        repository_root=Path("/repo"),
                    )

        self.assertIs(state, light_state)
        bootstrap.assert_called_once()


if __name__ == "__main__":
    unittest.main()
