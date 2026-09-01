from __future__ import annotations

from datetime import UTC, datetime
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch

from core.apps.contracts import parse_app_contract_file
from core.apps.registration import build_workspace_app_binding_record
from core.apps.service import register_app_source_from_contract
from core.apps.surface_descriptors import (
    app_cli_command_execution_metadata,
    app_mcp_tool_execution_metadata,
)
from core.cli.models import CliInvocationContext
from core.cli.registry_builder import build_core_cli_registry
from core.cli.runner import CliRunner
from core.mcp.models import McpInvocationContext
from core.mcp.registry_builder import build_core_mcp_registry
from core.mcp.runner import McpRunner
from core.runtime.hosted_tool_result_admission import (
    build_hosted_tool_result_preflight_resolver,
)
from core.runtime.tool_discovery_capabilities import RuntimeToolDiscoveryBroker
from core.runtime.tool_catalog import RuntimeToolActorContext
from tests.support.surfaces import SurfaceTestBase


REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
EFFECT_CLASSES = {"read", "mutating", "destructive"}


class BuiltinSurfaceEffectsTest(SurfaceTestBase):
    def test_every_builtin_app_surface_has_valid_effect_metadata(self) -> None:
        counts = {"cli": 0, "mcp": 0}
        argument_sensitive = 0
        for app_root in sorted((REPOSITORY_ROOT / "apps").iterdir()):
            if not (app_root / "app_contract.json").is_file():
                continue
            contract = parse_app_contract_file(app_root).contract
            for command_id in contract.capabilities.cli_commands:
                metadata = app_cli_command_execution_metadata(app_root, command_id)
                self.assertIn(
                    metadata.effect_class,
                    EFFECT_CLASSES,
                    f"{app_root.name} CLI {command_id}",
                )
                counts["cli"] += 1
                argument_sensitive += self._assert_argument_map_covers_schema(
                    app_root / "cli" / "command_schemas.json",
                    "commands",
                    command_id,
                    "argument_schema",
                    metadata,
                )
            for tool_name in contract.capabilities.mcp_tools:
                metadata = app_mcp_tool_execution_metadata(app_root, tool_name)
                self.assertIn(
                    metadata.effect_class,
                    EFFECT_CLASSES,
                    f"{app_root.name} MCP {tool_name}",
                )
                counts["mcp"] += 1
                argument_sensitive += self._assert_argument_map_covers_schema(
                    app_root / "mcp" / "tool_schemas.json",
                    "tools",
                    tool_name,
                    "input_schema",
                    metadata,
                )

        self.assertEqual(counts, {"cli": 28, "mcp": 383})
        self.assertEqual(argument_sensitive, 33)

    def test_real_storage_cli_and_mcp_catalog_execute_after_preflight(self) -> None:
        store = self.make_app_store()
        now = datetime.now(tz=UTC)
        source = register_app_source_from_contract(
            store,
            source_kind="platform",
            source_path=str(REPOSITORY_ROOT / "apps" / "storage"),
            now=now,
        )
        with TemporaryDirectory() as temp_dir:
            workspace_root = Path(temp_dir)
            data_root = workspace_root / "data"
            uploaded = workspace_root / "storage" / "uploaded"
            generated = workspace_root / "storage" / "generated"
            data_root.mkdir()
            uploaded.mkdir(parents=True)
            generated.mkdir(parents=True)
            store.save_workspace_app_binding(
                build_workspace_app_binding_record(
                    workspace_id="default",
                    app_id="storage",
                    source_record_id=source.source_id,
                    source_kind="platform",
                    status="enabled",
                    active_version=source.version,
                    data_root=str(data_root),
                    now=now,
                )
            )
            cli_context = CliInvocationContext(
                "full_access_agent",
                "default",
                "chat",
                "full-access",
                platform_role="admin",
                user_id="user-1",
                workspace_role="owner",
                runtime_session_id="session-storage",
            )
            mcp_context = McpInvocationContext(
                "full_access_agent",
                "default",
                "chat",
                "full-access",
                platform_role="admin",
                user_id="user-1",
                workspace_role="owner",
                runtime_session_id="session-storage",
            )
            paths = SimpleNamespace(
                root=workspace_root,
                uploaded_storage=uploaded,
                generated_storage=generated,
            )
            with patch(
                "core.cli.app_commands.workspace_paths",
                return_value=paths,
            ), patch(
                "core.mcp.app_tools.workspace_paths",
                return_value=paths,
            ):
                cli = build_core_cli_registry(
                    app_store=store,
                    workspace_id="default",
                    context=cli_context,
                    start_path=REPOSITORY_ROOT,
                )
                mcp = build_core_mcp_registry(
                    app_store=store,
                    workspace_id="default",
                    context=mcp_context,
                    start_path=REPOSITORY_ROOT,
                )

            actor = RuntimeToolActorContext(
                workspace_id="default",
                actor_id="user-1",
                agent_id="chat",
                platform_role="admin",
                workspace_role="owner",
                session_id="session-storage",
                execution_mode="full-access",
            )
            preflight = build_hosted_tool_result_preflight_resolver(
                cli_registry=cli,
                mcp_registry=mcp,
            )
            discovery = RuntimeToolDiscoveryBroker(
                cli_registry=cli,
                mcp_registry=mcp,
            )
            discovered_cli = self._all_discovered(
                discovery.list_cli,
                "commands",
                actor,
            )
            discovered_mcp = self._all_discovered(
                discovery.list_mcp,
                "tools",
                actor,
            )
            self.assertIn(
                "effect_class_by_argument",
                next(
                    item
                    for item in discovered_cli
                    if item["command_id"] == "app.storage.storage"
                ),
            )
            self.assertIn(
                "effect_class_by_argument",
                next(
                    item
                    for item in discovered_mcp
                    if item["tool_name"] == "app.storage.maverick_storage"
                ),
            )
            cli_arguments = {
                "command_id": "app.storage.storage",
                "arguments": {"action": "catalog"},
            }
            mcp_arguments = {
                "tool_name": "app.storage.maverick_storage",
                "arguments": {"action": "catalog"},
            }
            self.assertTrue(
                preflight("core-capability:cli.run", cli_arguments, actor)
                .admitted_before_effect
            )
            self.assertTrue(
                preflight("core-capability:mcp.call", mcp_arguments, actor)
                .admitted_before_effect
            )
            self.assertFalse(
                preflight(
                    "core-capability:cli.run",
                    {
                        **cli_arguments,
                        "arguments": {"action": "write_file"},
                    },
                    actor,
                ).admitted_before_effect
            )

            cli_result = CliRunner(cli).run_command(
                command_id="app.storage.storage",
                arguments={"action": "catalog"},
                context=cli_context,
            )
            mcp_result = McpRunner(mcp).call_tool(
                tool_name="app.storage.maverick_storage",
                arguments={"action": "catalog"},
                context=mcp_context,
            )

            self.assertEqual(cli_result["status_code"], 200)
            self.assertEqual(mcp_result["status_code"], 200)
            self.assertEqual(cli_result["files"], [])
            self.assertEqual(mcp_result["files"], [])

    def _assert_argument_map_covers_schema(
        self,
        path: Path,
        root_field: str,
        item_name: str,
        schema_field: str,
        metadata,
    ) -> int:
        if metadata.argument_effects is None:
            return 0
        item = json.loads(path.read_text(encoding="utf-8"))[root_field][item_name]
        properties = item.get(schema_field, {}).get("properties", {})
        discriminator = properties.get(metadata.argument_effects.argument_name, {})
        values = discriminator.get("enum")
        if isinstance(values, list):
            self.assertEqual(
                set(values),
                {value for value, _effect in metadata.argument_effects.value_effect_classes},
                f"{path}:{item_name}",
            )
        return 1

    @staticmethod
    def _all_discovered(method, field_name: str, actor) -> list[dict[str, object]]:
        items: list[dict[str, object]] = []
        cursor = 0
        while True:
            payload = method({"cursor": cursor}, actor, None).payload
            items.extend(payload[field_name])
            next_cursor = payload["next_cursor"]
            if next_cursor is None:
                return items
            cursor = next_cursor


if __name__ == "__main__":
    import unittest

    unittest.main()
