"""Tests for Maverick CLI wrapper bootstrap selection."""

from __future__ import annotations

import unittest

from core.app_sdk.cli import _bootstrap_options_for_cli


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


if __name__ == "__main__":
    unittest.main()
