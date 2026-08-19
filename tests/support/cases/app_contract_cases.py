"""Tests for canonical app contract parsing and contract support."""

from __future__ import annotations

from pathlib import Path
import json
from tempfile import TemporaryDirectory
import unittest

from core.apps.contracts import (
    app_contract_path,
    build_app_capabilities,
    build_app_compatibility,
    build_app_contract,
    build_app_distribution,
    build_app_entrypoints,
    build_app_hook_timeouts,
    build_app_lifecycle,
    build_app_permissions,
    build_app_presentation,
    build_reference_entity_declaration,
    build_app_storage,
    build_parsed_app_contract,
    build_provided_interface_declaration,
    build_widget_actions,
    build_widget_declaration,
    build_widget_frontend,
    build_required_interface_declaration,
    build_view_state_action_declaration,
    build_view_surface_declaration,
    parse_app_contract_file,
    write_app_contract_file,
)
from core.apps.contract_serializer import app_contract_payload
from core.apps.errors import AppContractValidationError
from core.apps.lifecycle import run_lifecycle_hook


class AppContractTestCase(unittest.TestCase):
    """Verify canonical contract-file parsing, validation, and timeout-backed hook execution."""

    def test_repository_app_contracts_are_canonical(self) -> None:
        apps_root = Path(__file__).resolve().parents[3] / "apps"
        for contract_path in sorted(apps_root.glob("*/app_contract.json")):
            with self.subTest(app=contract_path.parent.name):
                parsed = parse_app_contract_file(contract_path.parent)
                raw = json.loads(contract_path.read_text(encoding="utf-8"))
                self.assertEqual(raw, app_contract_payload(parsed))

    def test_lifecycle_rebuild_field_is_rejected(self) -> None:
        with TemporaryDirectory() as temp_dir:
            app_root = Path(temp_dir) / "apps" / "legacy-rebuild"
            parsed = build_parsed_app_contract(
                app_id="legacy_rebuild",
                name="Legacy Rebuild",
                version="1.0.0",
                description="Invalid app with old rebuild flag.",
                publisher="test",
                contract=build_app_contract(),
            )
            write_app_contract_file(app_root, parsed)
            payload = json.loads((app_root / "app_contract.json").read_text(encoding="utf-8"))
            payload["lifecycle"]["rebuild"] = True
            (app_root / "app_contract.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")

            with self.assertRaises(AppContractValidationError):
                parse_app_contract_file(app_root)

    def test_parse_contract_file_supports_storage_capabilities_and_lifecycle(self) -> None:
        with TemporaryDirectory() as temp_dir:
            app_root = Path(temp_dir) / "apps" / "restaurant-manager"
            (app_root / "backend" / "mcp").mkdir(parents=True, exist_ok=True)
            (app_root / "backend" / "cli").mkdir(parents=True, exist_ok=True)
            (app_root / "backend" / "skills").mkdir(parents=True, exist_ok=True)
            (app_root / "backend" / "lifecycle").mkdir(parents=True, exist_ok=True)
            (app_root / "backend" / "mcp" / "server.py").write_text("print('mcp')\n", encoding="utf-8")
            (app_root / "backend" / "cli" / "app_cli.py").write_text("print('cli')\n", encoding="utf-8")
            (app_root / "backend" / "lifecycle" / "install.py").write_text("print('install')\n", encoding="utf-8")
            (app_root / "backend" / "lifecycle" / "health.py").write_text("print('health')\n", encoding="utf-8")
            parsed = build_parsed_app_contract(
                app_id="restaurant_manager",
                name="Restaurant Manager",
                version="1.2.0",
                description="Manage rooms and tables.",
                publisher="third-party-dev",
                contract=build_app_contract(
                    compatibility=build_app_compatibility(supported_workspace_modes=["sandbox", "full-access"]),
                    storage=build_app_storage(
                        storage_kind="sqlite",
                        primary_paths=["data/restaurant-manager/app.db"],
                        indices_kind="embedded",
                        supports_export=True,
                        supports_import=True,
                        supports_migrations=True,
                    ),
                    capabilities=build_app_capabilities(
                        mcp_tools=["tables.list"],
                        cli_commands=["tables"],
                        skills=["restaurant-operations"],
                        views=["floor_map"],
                        reference_entities=[
                            build_reference_entity_declaration(
                                entity_type="reservation",
                                display_name="Reservation",
                            )
                        ],
                        view_surfaces=[
                            build_view_surface_declaration(
                                view_id="floor_map",
                                display_name="Floor Map",
                                entity_types=["reservation"],
                                state_actions=[
                                    build_view_state_action_declaration(
                                        action="view_state",
                                        standard=True,
                                        description="Read current view state.",
                                    ),
                                    build_view_state_action_declaration(
                                        action="set_custom_view",
                                        standard=True,
                                        description="Render a curated reservation set.",
                                    ),
                                    build_view_state_action_declaration(
                                        action="floor_heatmap",
                                        standard=False,
                                        description="Toggle app-specific floor heatmap data.",
                                    ),
                                ],
                                supports_custom_view=True,
                                supports_filter_refinement=True,
                            )
                        ],
                    ),
                    lifecycle=build_app_lifecycle(
                        migrate=True,
                        export=True,
                        import_data=True,
                        validate_after_import=True,
                        repair_after_import=True,
                        health_check=True,
                    ),
                    permissions=build_app_permissions(
                        secret_read=["oauth-account"],
                        secret_write=["oauth-account"],
                        network_outbound=["api.vendor.example"],
                        runtime_cleanup_sessions=True,
                        runtime_receive_cleanup_callbacks=True,
                        host_telemetry=True,
                    ),
                    entrypoints=build_app_entrypoints(
                        mcp="backend/mcp/server.py",
                        cli="backend/cli/app_cli.py",
                        skills_root="backend/skills",
                        hooks={
                            "install": "backend/lifecycle/install.py",
                            "health_check": "backend/lifecycle/health.py",
                        },
                    ),
                    hook_timeouts=build_app_hook_timeouts(
                        backend_seconds=240,
                        upgrade_seconds=180,
                        validate_after_import_seconds=45,
                        repair_after_import_seconds=90,
                    ),
                    provides=[
                        build_provided_interface_declaration(
                            interface="reservation.catalog",
                            description="Reservation catalog interface.",
                            surfaces=["cli", "mcp", "reference", "view"],
                        )
                    ],
                    requires=[
                        build_required_interface_declaration(
                            alias="kitchen-display",
                            interface="kitchen.display",
                            description="Optional kitchen display provider.",
                            required=False,
                            cardinality="one",
                        )
                    ],
                ),
            )
            write_app_contract_file(app_root, parsed)

            loaded = parse_app_contract_file(app_root)

            self.assertEqual(loaded.app_id, "restaurant-manager")
            self.assertEqual(loaded.contract.storage.storage_kind, "sqlite")
            self.assertEqual(loaded.contract.storage.indices.kind, "embedded")
            self.assertEqual(loaded.contract.capabilities.views, ["floor_map"])
            self.assertEqual(loaded.contract.capabilities.view_surfaces[0].view_id, "floor_map")
            self.assertEqual(loaded.contract.capabilities.view_surfaces[0].entity_types, ["reservation"])
            actions = {item.action: item for item in loaded.contract.capabilities.view_surfaces[0].state_actions}
            self.assertTrue(actions["set_custom_view"].standard)
            self.assertFalse(actions["floor_heatmap"].standard)
            self.assertTrue(loaded.contract.capabilities.view_surfaces[0].supports_custom_view)
            self.assertEqual(loaded.contract.capabilities.reference_entities[0].entity_type, "reservation")
            self.assertTrue(loaded.contract.capabilities.reference_entities[0].searchable)
            self.assertEqual(loaded.contract.capabilities.reference_entities[0].cache_scope, "session")
            self.assertEqual(loaded.contract.distribution.mode, "sealed")
            self.assertEqual(loaded.contract.distribution.source_access, "none")
            self.assertTrue(loaded.contract.lifecycle.validate_after_import)
            self.assertTrue(loaded.contract.lifecycle.repair_after_import)
            self.assertEqual(loaded.contract.hook_timeouts.backend_seconds, 240)
            self.assertEqual(loaded.contract.hook_timeouts.upgrade_seconds, 180)
            self.assertEqual(loaded.contract.hook_timeouts.validate_after_import_seconds, 45)
            self.assertEqual(loaded.contract.entrypoints.skills_root, "backend/skills")
            self.assertEqual(loaded.contract.provides[0].interface, "reservation.catalog")
            self.assertEqual(loaded.contract.requires[0].alias, "kitchen-display")
            self.assertEqual(loaded.contract.permissions.secrets.read, ["oauth-account"])
            self.assertEqual(loaded.contract.permissions.network.outbound, ["api.vendor.example"])
            self.assertTrue(loaded.contract.permissions.runtime.cleanup_sessions)
            self.assertTrue(loaded.contract.permissions.runtime.receive_cleanup_callbacks)
            self.assertTrue(loaded.contract.permissions.host.telemetry)

    def test_parse_contract_preserves_frontend_presentation_role(self) -> None:
        with TemporaryDirectory() as temp_dir:
            app_root = Path(temp_dir) / "apps" / "supporting-tool"
            (app_root / "frontend" / "dist").mkdir(parents=True, exist_ok=True)
            parsed = build_parsed_app_contract(
                app_id="supporting-tool",
                name="Supporting Tool",
                version="1.0.0",
                description="Tool with mounted supporting frontend assets.",
                publisher="vendor",
                contract=build_app_contract(
                    presentation=build_app_presentation(frontend_role="supporting"),
                    entrypoints=build_app_entrypoints(frontend="frontend/dist"),
                ),
            )
            write_app_contract_file(app_root, parsed)

            loaded = parse_app_contract_file(app_root)

            self.assertEqual(loaded.contract.presentation.frontend_role, "supporting")
            self.assertEqual(app_contract_payload(loaded)["presentation"], {"frontend_role": "supporting"})

    def test_parse_contract_rejects_frontend_role_without_matching_entrypoint(self) -> None:
        with TemporaryDirectory() as temp_dir:
            app_root = Path(temp_dir) / "apps" / "bad-presentation"
            parsed = build_parsed_app_contract(
                app_id="bad-presentation",
                name="Bad Presentation",
                version="1.0.0",
                description="Invalid presentation contract.",
                publisher="vendor",
                contract=build_app_contract(
                    presentation=build_app_presentation(frontend_role="supporting"),
                ),
            )
            write_app_contract_file(app_root, parsed)

            with self.assertRaisesRegex(AppContractValidationError, "frontend role requires"):
                parse_app_contract_file(app_root)

            (app_root / "frontend" / "dist").mkdir(parents=True, exist_ok=True)
            parsed = build_parsed_app_contract(
                app_id="bad-presentation",
                name="Bad Presentation",
                version="1.0.0",
                description="Invalid presentation contract.",
                publisher="vendor",
                contract=build_app_contract(
                    presentation=build_app_presentation(frontend_role="none"),
                    entrypoints=build_app_entrypoints(frontend="frontend/dist"),
                ),
            )
            write_app_contract_file(app_root, parsed)

            with self.assertRaisesRegex(AppContractValidationError, "must use frontend_role workspace or supporting"):
                parse_app_contract_file(app_root)

    def test_parse_contract_rejects_unknown_root_and_section_fields(self) -> None:
        with TemporaryDirectory() as temp_dir:
            app_root = Path(temp_dir) / "apps" / "strict-app"
            parsed = build_parsed_app_contract(
                app_id="strict-app",
                name="Strict",
                version="1.0.0",
                description="Strict app.",
                publisher="vendor",
            )
            write_app_contract_file(app_root, parsed)
            contract_path = app_contract_path(app_root)
            payload = json.loads(contract_path.read_text(encoding="utf-8"))

            root_payload = dict(payload)
            root_payload["frontend_policy"] = {"same_origin": True}
            contract_path.write_text(json.dumps(root_payload, indent=2) + "\n", encoding="utf-8")
            with self.assertRaisesRegex(AppContractValidationError, "Unsupported app_contract field"):
                parse_app_contract_file(app_root)

            section_payload = dict(payload)
            section_payload["permissions"] = {
                **section_payload["permissions"],
                "host": {**section_payload["permissions"]["host"], "process_list": True},
            }
            contract_path.write_text(json.dumps(section_payload, indent=2) + "\n", encoding="utf-8")
            with self.assertRaisesRegex(AppContractValidationError, "Unsupported permissions.host field"):
                parse_app_contract_file(app_root)

    def test_parse_contract_rejects_invalid_operational_permissions(self) -> None:
        with TemporaryDirectory() as temp_dir:
            app_root = Path(temp_dir) / "apps" / "privileged-app"
            parsed = build_parsed_app_contract(
                app_id="privileged-app",
                name="Privileged",
                version="1.0.0",
                description="Privileged app.",
                publisher="vendor",
                contract=build_app_contract(
                    permissions=build_app_permissions(secret_read=["Bad Alias"]),
                ),
            )
            write_app_contract_file(app_root, parsed)

            with self.assertRaisesRegex(AppContractValidationError, "permissions.secrets.read"):
                parse_app_contract_file(app_root)

    def test_parse_contract_rejects_invalid_required_interface_metadata(self) -> None:
        with TemporaryDirectory() as temp_dir:
            app_root = Path(temp_dir) / "apps" / "workflow"
            parsed = build_parsed_app_contract(
                app_id="workflow",
                name="Workflow",
                version="1.0.0",
                description="Workflow app.",
                publisher="vendor",
                contract=build_app_contract(
                    requires=[
                        build_required_interface_declaration(
                            alias="bad-cardinality",
                            interface="agent.catalog",
                            description="Agent provider.",
                            cardinality="one",
                        )
                    ]
                ),
            )
            write_app_contract_file(app_root, parsed)
            contract_path = app_contract_path(app_root)
            payload = json.loads(contract_path.read_text(encoding="utf-8"))
            payload["requires"][0]["cardinality"] = "several"
            contract_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")

            with self.assertRaises(AppContractValidationError):
                parse_app_contract_file(app_root)

    def test_parse_contract_rejects_invalid_provided_interface_surface(self) -> None:
        with TemporaryDirectory() as temp_dir:
            app_root = Path(temp_dir) / "apps" / "provider"
            parsed = build_parsed_app_contract(
                app_id="provider",
                name="Provider",
                version="1.0.0",
                description="Provider app.",
                publisher="vendor",
                contract=build_app_contract(
                    provides=[
                        build_provided_interface_declaration(
                            interface="file.catalog",
                            description="File provider.",
                            surfaces=["private-files"],
                        )
                    ]
                ),
            )
            write_app_contract_file(app_root, parsed)

            with self.assertRaises(AppContractValidationError):
                parse_app_contract_file(app_root)

    def test_parse_contract_rejects_invalid_reference_entity_metadata(self) -> None:
        with TemporaryDirectory() as temp_dir:
            app_root = Path(temp_dir) / "apps" / "reference-app"
            parsed = build_parsed_app_contract(
                app_id="reference-app",
                name="Reference App",
                version="1.0.0",
                description="Customer records.",
                publisher="vendor",
            )
            write_app_contract_file(app_root, parsed)
            contract_path = app_contract_path(app_root)
            payload = json.loads(contract_path.read_text(encoding="utf-8"))
            payload["capabilities"]["reference_entities"] = [
                {"entity_type": "Bad-Type", "display_name": "Bad"}
            ]
            contract_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")

            with self.assertRaises(AppContractValidationError):
                parse_app_contract_file(app_root)

    def test_parse_contract_rejects_view_surface_for_undeclared_entity_type(self) -> None:
        with TemporaryDirectory() as temp_dir:
            app_root = Path(temp_dir) / "apps" / "reference-app"
            parsed = build_parsed_app_contract(
                app_id="reference-app",
                name="Reference App",
                version="1.0.0",
                description="Customer records.",
                publisher="vendor",
                contract=build_app_contract(
                    capabilities=build_app_capabilities(
                        views=["reference"],
                        view_surfaces=[
                            build_view_surface_declaration(
                                view_id="reference",
                                display_name="Reference",
                                entity_types=["deal"],
                                state_actions=[
                                    build_view_state_action_declaration(
                                        action="set_custom_view",
                                        standard=True,
                                        description="Render a curated deal set.",
                                    )
                                ],
                                supports_custom_view=True,
                            )
                        ],
                    )
                ),
            )
            write_app_contract_file(app_root, parsed)

            with self.assertRaises(AppContractValidationError):
                parse_app_contract_file(app_root)

    def test_parse_contract_rejects_view_surface_for_undeclared_view(self) -> None:
        with TemporaryDirectory() as temp_dir:
            app_root = Path(temp_dir) / "apps" / "reference-app"
            parsed = build_parsed_app_contract(
                app_id="reference-app",
                name="Reference App",
                version="1.0.0",
                description="Customer records.",
                publisher="vendor",
                contract=build_app_contract(
                    capabilities=build_app_capabilities(
                        views=["reference"],
                        reference_entities=[
                            build_reference_entity_declaration(entity_type="deal", display_name="Deal")
                        ],
                        view_surfaces=[
                            build_view_surface_declaration(
                                view_id="pipeline",
                                display_name="Pipeline",
                                entity_types=["deal"],
                                state_actions=[
                                    build_view_state_action_declaration(
                                        action="set_custom_view",
                                        standard=True,
                                        description="Render a curated deal set.",
                                    )
                                ],
                                supports_custom_view=True,
                            )
                        ],
                    )
                ),
            )
            write_app_contract_file(app_root, parsed)

            with self.assertRaises(AppContractValidationError):
                parse_app_contract_file(app_root)

    def test_parse_contract_supports_source_available_distribution(self) -> None:
        with TemporaryDirectory() as temp_dir:
            app_root = Path(temp_dir) / "apps" / "customizable"
            parsed = build_parsed_app_contract(
                app_id="customizable",
                name="Customizable",
                version="1.0.0",
                description="Customizable app.",
                publisher="vendor",
                contract=build_app_contract(
                    distribution=build_app_distribution(
                        mode="source_available",
                        source_access="forkable",
                    ),
                ),
            )
            write_app_contract_file(app_root, parsed)

            loaded = parse_app_contract_file(app_root)

            self.assertEqual(loaded.contract.distribution.mode, "source_available")
            self.assertEqual(loaded.contract.distribution.source_access, "forkable")

    def test_parse_contract_round_trips_widget_declarations(self) -> None:
        with TemporaryDirectory() as temp_dir:
            app_root = Path(temp_dir) / "apps" / "checklists"
            (app_root / "frontend" / "dist" / "widgets" / "design-checklist").mkdir(parents=True, exist_ok=True)
            (app_root / "backend").mkdir(parents=True, exist_ok=True)
            (app_root / "backend" / "app_backend.py").write_text("print('backend')\n", encoding="utf-8")
            parsed = build_parsed_app_contract(
                app_id="checklists",
                name="Checklists",
                version="1.0.0",
                description="Checklist widgets.",
                publisher="maverick",
                contract=build_app_contract(
                    entrypoints=build_app_entrypoints(backend="backend/app_backend.py"),
                    widgets=[
                        build_widget_declaration(
                            widget_id="design-checklist",
                            host="host-app",
                            content_kinds=["checklist.design"],
                            frontend=build_widget_frontend(
                                mount="frontend/dist/widgets/design-checklist",
                                spa_fallback=True,
                            ),
                            actions=build_widget_actions(backend=True),
                        )
                    ],
                ),
            )
            write_app_contract_file(app_root, parsed)

            loaded = parse_app_contract_file(app_root)

            self.assertEqual(len(loaded.contract.widgets), 1)
            widget = loaded.contract.widgets[0]
            self.assertEqual(widget.widget_id, "design-checklist")
            self.assertEqual(widget.host, "host-app")
            self.assertEqual(widget.content_kinds, ["checklist.design"])
            self.assertEqual(widget.frontend.mount, "frontend/dist/widgets/design-checklist")
            self.assertTrue(widget.actions.backend)

    def test_parse_contract_rejects_duplicate_widget_ids(self) -> None:
        with TemporaryDirectory() as temp_dir:
            app_root = Path(temp_dir) / "apps" / "widgets"
            widget_root = app_root / "frontend" / "dist" / "widgets" / "card"
            widget_root.mkdir(parents=True, exist_ok=True)
            parsed = build_parsed_app_contract(
                app_id="widgets",
                name="Widgets",
                version="1.0.0",
                description="Widget app.",
                publisher="maverick",
                contract=build_app_contract(
                    widgets=[
                        build_widget_declaration(
                            widget_id="card",
                            host="host-app",
                            content_kinds=["demo.card"],
                            frontend=build_widget_frontend(mount="frontend/dist/widgets/card"),
                        ),
                        build_widget_declaration(
                            widget_id="card",
                            host="host-app",
                            content_kinds=["demo.card"],
                            frontend=build_widget_frontend(mount="frontend/dist/widgets/card"),
                        ),
                    ]
                ),
            )
            write_app_contract_file(app_root, parsed)

            with self.assertRaises(AppContractValidationError):
                parse_app_contract_file(app_root)

    def test_parse_contract_rejects_unsafe_widget_mount(self) -> None:
        with TemporaryDirectory() as temp_dir:
            app_root = Path(temp_dir) / "apps" / "widgets"
            (app_root / "frontend" / "dist").mkdir(parents=True, exist_ok=True)
            parsed = build_parsed_app_contract(
                app_id="widgets",
                name="Widgets",
                version="1.0.0",
                description="Widget app.",
                publisher="maverick",
                contract=build_app_contract(
                    widgets=[
                        build_widget_declaration(
                            widget_id="card",
                            host="host-app",
                            content_kinds=["demo.card"],
                            frontend=build_widget_frontend(mount="../outside"),
                        )
                    ]
                ),
            )
            write_app_contract_file(app_root, parsed)

            with self.assertRaises(AppContractValidationError):
                parse_app_contract_file(app_root)

    def test_parse_contract_rejects_widget_actions_without_surface(self) -> None:
        with TemporaryDirectory() as temp_dir:
            app_root = Path(temp_dir) / "apps" / "widgets"
            (app_root / "frontend" / "dist" / "widgets" / "card").mkdir(parents=True, exist_ok=True)
            parsed = build_parsed_app_contract(
                app_id="widgets",
                name="Widgets",
                version="1.0.0",
                description="Widget app.",
                publisher="maverick",
                contract=build_app_contract(
                    widgets=[
                        build_widget_declaration(
                            widget_id="card",
                            host="host-app",
                            content_kinds=["demo.card"],
                            frontend=build_widget_frontend(mount="frontend/dist/widgets/card"),
                            actions=build_widget_actions(backend=True),
                        )
                    ]
                ),
            )
            write_app_contract_file(app_root, parsed)

            with self.assertRaises(AppContractValidationError):
                parse_app_contract_file(app_root)

    def test_parse_contract_rejects_invalid_distribution_policy(self) -> None:
        with TemporaryDirectory() as temp_dir:
            app_root = Path(temp_dir) / "apps" / "sealed"
            parsed = build_parsed_app_contract(
                app_id="sealed",
                name="Sealed",
                version="1.0.0",
                description="Sealed app.",
                publisher="vendor",
                contract=build_app_contract(
                    distribution=build_app_distribution(
                        mode="sealed",
                        source_access="forkable",
                    ),
                ),
            )
            write_app_contract_file(app_root, parsed)

            with self.assertRaises(AppContractValidationError):
                parse_app_contract_file(app_root)

    def test_parse_contract_rejects_unknown_distribution_fields(self) -> None:
        with TemporaryDirectory() as temp_dir:
            app_root = Path(temp_dir) / "apps" / "bad-field"
            parsed = build_parsed_app_contract(
                app_id="bad-field",
                name="Bad Field",
                version="1.0.0",
                description="Bad field app.",
                publisher="vendor",
                contract=build_app_contract(
                    distribution=build_app_distribution(mode="source_available", source_access="forkable"),
                ),
            )
            write_app_contract_file(app_root, parsed)
            contract_file = app_contract_path(app_root)
            payload = contract_file.read_text(encoding="utf-8").replace(
                '"source_access": "forkable"',
                '"source_access": "forkable",\n    "unexpected": true',
            )
            contract_file.write_text(payload, encoding="utf-8")

            with self.assertRaises(AppContractValidationError):
                parse_app_contract_file(app_root)

    def test_parse_contract_rejects_storage_outside_owned_namespace(self) -> None:
        with TemporaryDirectory() as temp_dir:
            app_root = Path(temp_dir) / "apps" / "unsafe"
            parsed = build_parsed_app_contract(
                app_id="unsafe",
                name="Unsafe",
                version="1.0.0",
                description="Unsafe app.",
                publisher="vendor",
                contract=build_app_contract(
                    storage=build_app_storage(
                        storage_kind="json",
                        primary_paths=["data/other-app/state.json"],
                    )
                ),
            )
            write_app_contract_file(app_root, parsed)

            with self.assertRaises(AppContractValidationError):
                parse_app_contract_file(app_root)

    def test_parse_contract_rejects_missing_contract_file(self) -> None:
        with TemporaryDirectory() as temp_dir:
            app_root = Path(temp_dir) / "apps" / "missing"
            app_root.mkdir(parents=True, exist_ok=True)

            with self.assertRaises(AppContractValidationError):
                parse_app_contract_file(app_root)

    def test_parse_contract_rejects_non_canonical_app_id(self) -> None:
        with TemporaryDirectory() as temp_dir:
            app_root = Path(temp_dir) / "apps" / "bad-app"
            parsed = build_parsed_app_contract(
                app_id="bad-app",
                name="Bad App",
                version="1.0.0",
                description="Bad app.",
                publisher="vendor",
            )
            write_app_contract_file(app_root, parsed)
            contract_file = app_contract_path(app_root)
            payload = contract_file.read_text(encoding="utf-8").replace('"bad-app"', '"bad_app"', 1)
            contract_file.write_text(payload, encoding="utf-8")

            with self.assertRaises(AppContractValidationError):
                parse_app_contract_file(app_root)

    def test_run_lifecycle_hook_uses_configured_timeout_mapping(self) -> None:
        with TemporaryDirectory() as temp_dir:
            repo_root = Path(temp_dir) / "maverick"
            for name in ("core", "apps", "workspaces"):
                (repo_root / name).mkdir(parents=True, exist_ok=True)
            (repo_root / "AGENTS.md").write_text("", encoding="utf-8")
            app_root = repo_root / "apps" / "validator"
            lifecycle_root = app_root / "backend" / "lifecycle"
            lifecycle_root.mkdir(parents=True, exist_ok=True)
            (lifecycle_root / "validate.py").write_text("print('validate')\n", encoding="utf-8")
            parsed = build_parsed_app_contract(
                app_id="validator",
                name="Validator",
                version="1.0.0",
                description="Validator app.",
                publisher="maverick",
                contract=build_app_contract(
                    lifecycle=build_app_lifecycle(validate_after_import=True),
                    entrypoints=build_app_entrypoints(
                        hooks={"validate_after_import": "backend/lifecycle/validate.py"}
                    ),
                ),
            )
            write_app_contract_file(app_root, parsed)
            loaded = parse_app_contract_file(app_root)

            run_lifecycle_hook(app_root, loaded.contract, hook_name="validate_after_import")

            self.assertTrue(app_contract_path(app_root).is_file())


if __name__ == "__main__":
    unittest.main()
