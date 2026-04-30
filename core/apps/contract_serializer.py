"""Serializer for canonical app contract files."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from core.apps.models import ParsedAppContract


from core.apps.contract_common import app_contract_path

def app_contract_payload(parsed: ParsedAppContract) -> dict[str, Any]:
    """Render one parsed contract into the canonical JSON payload shape."""
    lifecycle = parsed.contract.lifecycle
    payload = {
        "app_id": parsed.app_id,
        "contract_version": parsed.contract.compatibility.contract_version,
        "name": parsed.name,
        "version": parsed.version,
        "description": parsed.description,
        "publisher": parsed.publisher,
        "minimum_core_version": parsed.contract.compatibility.minimum_core_version,
        "provides": [
            {
                "interface": item.interface,
                "version": item.version,
                "description": item.description,
                "surfaces": item.surfaces,
            }
            for item in parsed.contract.provides
        ],
        "requires": [
            {
                "alias": item.alias,
                "interface": item.interface,
                "version": item.version,
                "required": item.required,
                "cardinality": item.cardinality,
                "description": item.description,
            }
            for item in parsed.contract.requires
        ],
        "distribution": {
            "mode": parsed.contract.distribution.mode,
            "source_access": parsed.contract.distribution.source_access,
        },
        "visibility": _visibility_payload(parsed),
        "permissions": {
            "secrets": {
                "read": parsed.contract.permissions.secrets.read,
                "write": parsed.contract.permissions.secrets.write,
            },
            "network": {
                "outbound": parsed.contract.permissions.network.outbound,
            },
            "runtime": {
                "create_sessions": parsed.contract.permissions.runtime.create_sessions,
                "cleanup_sessions": parsed.contract.permissions.runtime.cleanup_sessions,
            },
            "host": {
                "telemetry": parsed.contract.permissions.host.telemetry,
            },
        },
        "capabilities": {
            "mcp_tools": parsed.contract.capabilities.mcp_tools,
            "cli_commands": parsed.contract.capabilities.cli_commands,
            "skills": parsed.contract.capabilities.skills,
            "views": parsed.contract.capabilities.views,
            "data_events": [
                {
                    "resource": event.resource,
                    "description": event.description,
                }
                for event in parsed.contract.capabilities.data_events
            ],
            "view_surfaces": [
                {
                    "view_id": surface.view_id,
                    "display_name": surface.display_name,
                    "entity_types": surface.entity_types,
                    "state_actions": [
                        {
                            "action": action.action,
                            "standard": action.standard,
                            "description": action.description,
                        }
                        for action in surface.state_actions
                    ],
                    "supports_custom_view": surface.supports_custom_view,
                    "supports_filter_refinement": surface.supports_filter_refinement,
                }
                for surface in parsed.contract.capabilities.view_surfaces
            ],
            "reference_entities": [
                {
                    "entity_type": entity.entity_type,
                    "display_name": entity.display_name,
                    "searchable": entity.searchable,
                    "resolvable": entity.resolvable,
                    "summarizable": entity.summarizable,
                    "deep_link_supported": entity.deep_link_supported,
                }
                for entity in parsed.contract.capabilities.reference_entities
            ],
        },
        "entrypoints": {
            "mcp": parsed.contract.entrypoints.mcp,
            "cli": parsed.contract.entrypoints.cli,
            "backend": parsed.contract.entrypoints.backend,
            "frontend": parsed.contract.entrypoints.frontend,
            "skills_root": parsed.contract.entrypoints.skills_root,
            "hooks": parsed.contract.entrypoints.hooks,
        },
        "storage": {
            "storage_kind": parsed.contract.storage.storage_kind,
            "data_schema_version": parsed.contract.storage.data_schema_version,
            "primary_paths": parsed.contract.storage.primary_paths,
            "indices": (
                {"kind": parsed.contract.storage.indices.kind}
                if parsed.contract.storage.indices is not None
                else None
            ),
            "supports_export": parsed.contract.storage.supports_export,
            "supports_import": parsed.contract.storage.supports_import,
            "supports_migrations": parsed.contract.storage.supports_migrations,
        },
        "compatibility": {
            "workspace_modes": parsed.contract.compatibility.supported_workspace_modes or [],
        },
        "hook_timeouts": {
            "install_seconds": parsed.contract.hook_timeouts.install_seconds,
            "upgrade_seconds": parsed.contract.hook_timeouts.upgrade_seconds,
            "migrate_seconds": parsed.contract.hook_timeouts.migrate_seconds,
            "export_seconds": parsed.contract.hook_timeouts.export_seconds,
            "import_seconds": parsed.contract.hook_timeouts.import_seconds,
            "validate_after_import_seconds": parsed.contract.hook_timeouts.validate_after_import_seconds,
            "repair_after_import_seconds": parsed.contract.hook_timeouts.repair_after_import_seconds,
            "health_check_seconds": parsed.contract.hook_timeouts.health_check_seconds,
        },
        "lifecycle": {
            "install": lifecycle.install,
            "upgrade": lifecycle.upgrade,
            "uninstall": lifecycle.uninstall,
            "migrate": lifecycle.migrate,
            "export": lifecycle.export,
            "import": lifecycle.import_data,
            "validate_after_import": lifecycle.validate_after_import,
            "repair_after_import": lifecycle.repair_after_import,
            "health_check": lifecycle.health_check,
        },
        "health_contract": {
            "mode": parsed.contract.health_contract.mode,
            "degraded_on_failure": parsed.contract.health_contract.degraded_on_failure,
        },
        "failure_semantics": {
            "install_failure": parsed.contract.failure_semantics.install_failure,
            "migrate_failure": parsed.contract.failure_semantics.migrate_failure,
            "import_failure": parsed.contract.failure_semantics.import_failure,
        },
        "rollback_support": {
            "bundle": parsed.contract.rollback_support.bundle,
            "data": parsed.contract.rollback_support.data,
            "repair_only": parsed.contract.rollback_support.repair_only,
        },
    }
    payload["widgets"] = [
        {
            "widget_id": widget.widget_id,
            "host": widget.host,
            "content_kinds": widget.content_kinds,
            "frontend": {
                "kind": widget.frontend.kind,
                "mount": widget.frontend.mount,
                "spa_fallback": widget.frontend.spa_fallback,
            },
            "actions": {
                "backend": widget.actions.backend,
                "mcp": widget.actions.mcp,
                "cli": widget.actions.cli,
            },
        }
        for widget in parsed.contract.widgets
    ]
    return payload


def _visibility_payload(parsed: ParsedAppContract) -> dict[str, object]:
    payload: dict[str, object] = {"platform_roles": parsed.contract.visibility.platform_roles}
    if parsed.contract.visibility.workspace_roles is not None:
        payload["workspace_roles"] = parsed.contract.visibility.workspace_roles
    if parsed.contract.visibility.capabilities is not None:
        payload["capabilities"] = parsed.contract.visibility.capabilities
    return payload

def write_app_contract_file(source_root: Path, parsed: ParsedAppContract) -> Path:
    """Write one canonical app contract file into the given app root."""
    source_root.mkdir(parents=True, exist_ok=True)
    contract_file = app_contract_path(source_root)
    contract_file.write_text(json.dumps(app_contract_payload(parsed), indent=2) + "\n", encoding="utf-8")
    return contract_file
