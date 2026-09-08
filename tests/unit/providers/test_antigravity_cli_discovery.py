"""Authenticated, fail-closed catalog discovery for Antigravity CLI."""

from dataclasses import replace
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from core.providers.native_agent_discovery import (
    discover_antigravity_native_catalog,
)
from core.providers.native_agent_reconciliation import (
    refresh_antigravity_native_catalog,
)
from core.providers.native_runtime_artifact import (
    ANTIGRAVITY_CLI_RUNTIME_ARTIFACT,
)
from core.providers.service import builtin_provider_registry


class AntigravityCliDiscoveryTest(unittest.TestCase):
    def setUp(self) -> None:
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.root = Path(folder.name)
        self.source = self.root / "operator-profile"
        self.source.mkdir(mode=0o700)
        token = self.source / "antigravity-oauth-token"
        token.write_text("synthetic-oauth-token", encoding="utf-8")
        token.chmod(0o600)
        self.command = self.root / "agy-fixture"
        self.command.write_text(
            """#!/bin/sh
test "$1" = "models" || exit 90
test -f "$HOME/.gemini/antigravity-cli/antigravity-oauth-token" || exit 91
test -f "$HOME/.gemini/antigravity-cli/settings.json" || exit 92
test -z "${GEMINI_API_KEY+x}" || exit 93
test -z "${MAVERICK_PROVIDER_SECRET+x}" || exit 94
grep -q modelProvider "$HOME/.gemini/antigravity-cli/settings.json" && exit 95
printf 'Fetching available models...\\n'
printf 'gemini-3.8-flash-high\\tGemini 3.8 Flash (High)\\n'
printf 'claude-sonnet-4-6\\tClaude Sonnet 4.6 (Thinking)\\n'
""",
            encoding="utf-8",
        )
        self.command.chmod(0o755)
        self.adapter = SimpleNamespace(
            command=str(self.command),
            auth_home=self.source,
        )

    def discover(self):
        with patch(
            "core.providers.native_agent_discovery.inspect_native_runtime_artifact",
            return_value=ANTIGRAVITY_CLI_RUNTIME_ARTIFACT,
        ), patch(
            "core.providers.native_agent_discovery.build_bwrap_command",
            side_effect=lambda **values: values["command"],
        ):
            return discover_antigravity_native_catalog(
                self.adapter,
                force=True,
            )

    def test_private_oauth_catalog_discovery_publishes_exact_slugs(self) -> None:
        snapshot = self.discover()

        self.assertIsNotNone(snapshot)
        self.assertEqual(snapshot.runtime_engine_id, "antigravity-cli")
        self.assertEqual(snapshot.model_provider_id, "google")
        self.assertEqual(
            [model.model_id for model in snapshot.models],
            ["gemini-3.8-flash-high", "claude-sonnet-4-6"],
        )
        self.assertTrue(
            all(model.revision_policy == "provider_alias" for model in snapshot.models)
        )
        self.assertEqual(
            snapshot.model_options[0].metadata["native_model_catalog_digest"],
            snapshot.models[0].digest,
        )

    def test_wrong_binary_or_malformed_catalog_grants_no_availability(self) -> None:
        with patch(
            "core.providers.native_agent_discovery.inspect_native_runtime_artifact",
            return_value=replace(
                ANTIGRAVITY_CLI_RUNTIME_ARTIFACT,
                version="unreviewed",
            ),
        ), patch("core.providers.native_agent_discovery.subprocess.run") as run:
            self.assertIsNone(
                discover_antigravity_native_catalog(self.adapter, force=True)
            )
            run.assert_not_called()

        malformed = SimpleNamespace(
            stdout="Fetching available models...\nnot-a-tabular-record\n",
            stderr="",
        )
        with patch(
            "core.providers.native_agent_discovery.inspect_native_runtime_artifact",
            return_value=ANTIGRAVITY_CLI_RUNTIME_ARTIFACT,
        ), patch(
            "core.providers.native_agent_discovery.build_bwrap_command",
            side_effect=lambda **values: values["command"],
        ), patch(
            "core.providers.native_agent_discovery.subprocess.run",
            return_value=malformed,
        ):
            self.assertIsNone(
                discover_antigravity_native_catalog(self.adapter, force=True)
            )

    def test_refresh_updates_diagnostics_but_keeps_candidate_disabled(self) -> None:
        snapshot = self.discover()
        self.assertIsNotNone(snapshot)
        with patch(
            "core.providers.native_agent_reconciliation.discover_codex_native_catalog",
            return_value=None,
        ), patch(
            "core.providers.native_agent_reconciliation.discover_antigravity_native_catalog",
            return_value=None,
        ):
            registry = builtin_provider_registry()
        with patch(
            "core.providers.native_agent_reconciliation.discover_antigravity_native_catalog",
            return_value=snapshot,
        ):
            self.assertTrue(
                refresh_antigravity_native_catalog(registry, force=True)
            )

        definition = registry.get_provider_definition("antigravity-cli")
        self.assertEqual(definition.status, "disabled")
        self.assertEqual(
            [option.model_id for option in definition.model_options],
            ["gemini-3.8-flash-high", "claude-sonnet-4-6"],
        )
        self.assertIsNotNone(
            registry.get_native_agent_catalog("antigravity-cli", "google")
        )


if __name__ == "__main__":
    unittest.main()
