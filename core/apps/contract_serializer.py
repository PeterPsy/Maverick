"""Serializer for canonical app contract files."""

from __future__ import annotations

import json
from pathlib import Path
import re
from typing import Any

from core.apps.models import ParsedAppContract


CURRENT_APP_CONTRACT_VERSION = "1.0"
APP_CONTRACT_FILENAME = "app_contract.json"
APP_ID_PATTERN = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")

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
        "distribution": {
            "mode": parsed.contract.distribution.mode,
            "source_access": parsed.contract.distribution.source_access,
        },
        "visibility": {
            "platform_roles": parsed.contract.visibility.platform_roles,
        },
        "capabilities": {
            "mcp_tools": parsed.contract.capabilities.mcp_tools,
            "cli_commands": parsed.contract.capabilities.cli_commands,
            "skills": parsed.contract.capabilities.skills,
            "views": parsed.contract.capabilities.views,
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
            "rebuild": lifecycle.rebuild,
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
    if parsed.contract.widgets:
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

def write_app_contract_file(source_root: Path, parsed: ParsedAppContract) -> Path:
    """Write one canonical app contract file into the given app root."""
    source_root.mkdir(parents=True, exist_ok=True)
    contract_file = app_contract_path(source_root)
    contract_file.write_text(json.dumps(app_contract_payload(parsed), indent=2) + "\n", encoding="utf-8")
    return contract_file
