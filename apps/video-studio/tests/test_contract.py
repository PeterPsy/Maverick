"""Contract and descriptor tests for the installation-level Video Studio app."""

from __future__ import annotations

import json
from pathlib import Path
import unittest

from core.app_sdk.service import validate_app_source
from core.apps.contracts import parse_app_contract_file


APP_ROOT = Path(__file__).resolve().parents[1]


class VideoStudioContractTest(unittest.TestCase):
    def test_contract_parses_as_installation_level_source(self) -> None:
        parsed = parse_app_contract_file(APP_ROOT)

        self.assertEqual(parsed.app_id, "video-studio")
        self.assertEqual(parsed.publisher, "maverick")
        self.assertEqual(parsed.contract.distribution.mode, "source_available")
        self.assertEqual(parsed.contract.distribution.source_access, "forkable")
        self.assertEqual(parsed.contract.storage.storage_kind, "sqlite")
        self.assertEqual(parsed.contract.storage.primary_paths, ["data/video-studio/app.db"])
        self.assertTrue(parsed.contract.storage.supports_migrations)
        self.assertFalse(parsed.contract.storage.supports_export)
        self.assertFalse(parsed.contract.storage.supports_import)

    def test_contract_declares_implemented_project_revision_surfaces(self) -> None:
        parsed = parse_app_contract_file(APP_ROOT)
        contract = parsed.contract

        self.assertEqual(contract.capabilities.cli_commands, ["video-studio"])
        self.assertEqual(len(contract.capabilities.mcp_tools), 16)
        self.assertIn("video_studio_operations_apply", contract.capabilities.mcp_tools)
        self.assertIn("video_studio_native_import", contract.capabilities.mcp_tools)
        self.assertEqual(contract.capabilities.skills, ["video-studio-ops"])
        self.assertEqual(
            {event.resource for event in contract.capabilities.data_events},
            {"projects", "project-metadata", "revisions"},
        )
        self.assertEqual(contract.capabilities.reference_entities, [])
        self.assertEqual(contract.capabilities.view_surfaces, [])
        self.assertEqual(
            set(contract.entrypoints.hooks),
            {"install", "migrate", "health_check"},
        )
        self.assertTrue(contract.lifecycle.install)
        self.assertTrue(contract.lifecycle.migrate)
        self.assertTrue(contract.lifecycle.health_check)
        self.assertFalse(contract.lifecycle.export)
        self.assertFalse(contract.lifecycle.import_data)

    def test_storage_requirements_are_typed_and_provider_agnostic(self) -> None:
        parsed = parse_app_contract_file(APP_ROOT)
        requirements = {item.alias: item for item in parsed.contract.requires}

        self.assertEqual(
            {item.interface for item in requirements.values()},
            {
                "file.catalog",
                "file.preview",
                "file.content.read",
                "file.text.read",
                "file.content.write",
                "file.media.stream",
                "file.local.path",
            },
        )
        self.assertTrue(all(item.required for item in requirements.values()))
        self.assertTrue(all(item.cardinality == "one" for item in requirements.values()))
        self.assertTrue(all(item.version == "^1" for item in requirements.values()))

    def test_governed_sidecar_is_read_only_and_fail_closed(self) -> None:
        sidecars = parse_app_contract_file(APP_ROOT).contract.services.http_sidecars
        self.assertEqual(len(sidecars), 1)
        sidecar = sidecars[0]

        self.assertEqual(sidecar.service_id, "foundation")
        self.assertEqual(sidecar.process_policy.sandbox, "required")
        self.assertTrue(sidecar.process_policy.bundle_read_only)
        self.assertFalse(sidecar.process_policy.inherit_host_env)
        self.assertEqual(sidecar.process_policy.network, "isolated")
        self.assertEqual(sidecar.process_policy.outbound, [])
        self.assertIsNone(sidecar.entrypoint_access)
        self.assertIsNotNone(sidecar.proxy)
        assert sidecar.proxy is not None
        self.assertEqual(
            {(rule.method, rule.path_template) for rule in sidecar.proxy.route_policy.pass_through},
            {("GET", "/health"), ("GET", "/schema"), ("GET", "/status")},
        )

    def test_sdk_completeness_validation_passes(self) -> None:
        result = validate_app_source(APP_ROOT)
        self.assertTrue(result.valid, [issue.message for issue in result.issues])

    def test_descriptors_match_declared_executable_surfaces(self) -> None:
        cli = json.loads((APP_ROOT / "cli" / "command_schemas.json").read_text(encoding="utf-8"))
        mcp = json.loads((APP_ROOT / "mcp" / "tool_schemas.json").read_text(encoding="utf-8"))

        self.assertEqual(set(cli["commands"]), {"video-studio"})
        self.assertEqual(set(mcp["tools"]), set(parse_app_contract_file(APP_ROOT).contract.capabilities.mcp_tools))
        expected_actions = {
            "status", "schema", "health", "capabilities", "project.create",
            "project.list", "project.get", "project.rename", "project.duplicate",
            "project.archive", "project.restore", "revision.get", "revision.compare",
            "native.export", "native.import", "operations.apply", "history.undo", "history.redo",
        }
        self.assertEqual(
            set(cli["commands"]["video-studio"]["argument_schema"]["properties"]["action"]["enum"]),
            expected_actions,
        )
        self.assertEqual(
            set(mcp["tools"]["video_studio_foundation"]["input_schema"]["properties"]["action"]["enum"]),
            {"status", "schema", "health", "capabilities"},
        )
        for tool in mcp["tools"].values():
            self.assertEqual(tool["input_schema"].get("additionalProperties"), False)

    def test_docs_do_not_prescribe_workspace_local_installation(self) -> None:
        contract_text = (APP_ROOT / "app_contract.json").read_text(encoding="utf-8")
        readme_text = (APP_ROOT / "README.md").read_text(encoding="utf-8")
        for forbidden in ("register-local", "install-local"):
            self.assertNotIn(forbidden, contract_text)
            self.assertNotIn(forbidden, readme_text)


if __name__ == "__main__":
    unittest.main()
