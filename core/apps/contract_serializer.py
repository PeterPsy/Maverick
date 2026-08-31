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
        "presentation": {
            "frontend_role": parsed.contract.presentation.frontend_role,
        },
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
                **(
                    {"receive_cleanup_callbacks": True}
                    if parsed.contract.permissions.runtime.receive_cleanup_callbacks
                    else {}
                ),
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
                    **({"cache_scope": entity.cache_scope} if entity.cache_scope != "session" else {}),
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
        "hook_timeouts": _hook_timeouts_payload(parsed),
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
    provider_permissions = parsed.contract.permissions.providers
    if (
        provider_permissions.model_proxy
        or provider_permissions.credential_source != "none"
        or provider_permissions.deliver_secrets_to_app
    ):
        payload["permissions"]["providers"] = {
            "model_proxy": provider_permissions.model_proxy,
            "credential_source": provider_permissions.credential_source,
            "deliver_secrets_to_app": provider_permissions.deliver_secrets_to_app,
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
    if parsed.contract.services.http_sidecars:
        payload["services"] = {
            "http_sidecars": [
                {
                    "id": sidecar.service_id,
                    "runtime": sidecar.runtime,
                    **({"package_manager": sidecar.package_manager} if sidecar.package_manager is not None else {}),
                    "working_directory": sidecar.working_directory,
                    "command": sidecar.command,
                    "env": sidecar.env,
                    **(
                        {
                            "artifact_mounts": [
                                {"id": mount.artifact_id, "mount_path": mount.mount_path}
                                for mount in sidecar.artifact_mounts
                            ]
                        }
                        if sidecar.artifact_mounts
                        else {}
                    ),
                    **(
                        {
                            "root_filesystem": {
                                "artifact_id": sidecar.root_filesystem.artifact_id,
                                "subpath": sidecar.root_filesystem.subpath,
                            }
                        }
                        if sidecar.root_filesystem is not None
                        else {}
                    ),
                    **(
                        {"data_mount": {"subpath": sidecar.data_mount.subpath}}
                        if sidecar.data_mount is not None
                        else {}
                    ),
                    **(
                        {
                            "host_prepare": {
                                "entrypoint": sidecar.host_prepare.entrypoint,
                                "timeout_seconds": sidecar.host_prepare.timeout_seconds,
                                "environment_keys": sidecar.host_prepare.environment_keys,
                            }
                        }
                        if sidecar.host_prepare is not None
                        else {}
                    ),
                    **(
                        {
                            "model_access": {
                                "api": sidecar.model_access.api,
                                "cli": sidecar.model_access.cli,
                                "required": sidecar.model_access.required,
                            }
                        }
                        if sidecar.model_access is not None
                        else {}
                    ),
                    **(
                        {
                            "prewarm": {
                                "on_core_start": sidecar.prewarm.on_core_start,
                                "on_install": sidecar.prewarm.on_install,
                                "on_activation": sidecar.prewarm.on_activation,
                                "keep_alive": sidecar.prewarm.keep_alive,
                            }
                        }
                        if sidecar.prewarm is not None
                        else {}
                    ),
                    **(
                        {"diagnostics": {"status_file": sidecar.diagnostics.status_file}}
                        if sidecar.diagnostics is not None
                        else {}
                    ),
                    "process_policy": {
                        "inherit_host_env": sidecar.process_policy.inherit_host_env,
                        "sandbox": sidecar.process_policy.sandbox,
                        "bundle_read_only": sidecar.process_policy.bundle_read_only,
                        "workspace_data_write": sidecar.process_policy.workspace_data_write,
                        "network": sidecar.process_policy.network,
                        "transport": sidecar.process_policy.transport,
                        "outbound": sidecar.process_policy.outbound,
                        "limits": {
                            "memory_bytes": sidecar.process_policy.limits.memory_bytes,
                            "open_files": sidecar.process_policy.limits.open_files,
                            "request_concurrency": sidecar.process_policy.limits.request_concurrency,
                        },
                    },
                    **(
                        {
                            "browser_origin": {
                                "mode": sidecar.browser_origin.mode,
                                "csp_profile": sidecar.browser_origin.csp_profile,
                                "frame_ancestors": sidecar.browser_origin.frame_ancestors,
                                "connect_src": sidecar.browser_origin.connect_src,
                                **(
                                    {"immutable_asset_prefixes": sidecar.browser_origin.immutable_asset_prefixes}
                                    if sidecar.browser_origin.immutable_asset_prefixes
                                    else {}
                                ),
                                **(
                                    {
                                        "sandboxed_frame_resource_prefixes":
                                            sidecar.browser_origin.sandboxed_frame_resource_prefixes
                                    }
                                    if sidecar.browser_origin.sandboxed_frame_resource_prefixes
                                    else {}
                                ),
                            }
                        }
                        if sidecar.browser_origin is not None
                        else {}
                    ),
                    **(
                        {
                            "entrypoint_access": {
                                "ttl_seconds": sidecar.entrypoint_access.ttl_seconds,
                                "request_budget": sidecar.entrypoint_access.request_budget,
                                "max_request_body_bytes": sidecar.entrypoint_access.max_request_body_bytes,
                                "max_response_body_bytes": sidecar.entrypoint_access.max_response_body_bytes,
                                "streaming": sidecar.entrypoint_access.streaming,
                                "surfaces": [
                                    {
                                        "surface": surface.surface,
                                        "routes": [
                                            _http_sidecar_route_rule_payload(rule)
                                            for rule in surface.routes
                                        ],
                                    }
                                    for surface in sidecar.entrypoint_access.surfaces
                                ],
                            }
                        }
                        if sidecar.entrypoint_access is not None
                        else {}
                    ),
                    "bind": {
                        "host": sidecar.bind.host,
                        "port": sidecar.bind.port,
                    },
                    "health": {
                        "path": sidecar.health.path,
                        "timeout_ms": sidecar.health.timeout_ms,
                    },
                    **({"proxy": _http_sidecar_proxy_payload(sidecar.proxy)} if sidecar.proxy is not None else {}),
                    **(
                        {
                            "logs": {
                                "stdout": sidecar.logs.stdout,
                                "stderr": sidecar.logs.stderr,
                            }
                        }
                        if sidecar.logs is not None
                        else {}
                    ),
                }
                for sidecar in parsed.contract.services.http_sidecars
            ],
        }
    return payload


def _http_sidecar_proxy_payload(proxy) -> dict[str, object]:
    return {
        "mount": proxy.mount,
        "streaming": proxy.streaming,
        "sse": proxy.sse,
        "websocket": proxy.websocket,
        "route_policy": {
            "pass_through": [_http_sidecar_route_rule_payload(rule) for rule in proxy.route_policy.pass_through],
            "handled_by_core": [_http_sidecar_route_rule_payload(rule) for rule in proxy.route_policy.handled_by_core],
            "blocked": [_http_sidecar_route_rule_payload(rule) for rule in proxy.route_policy.blocked],
        },
    }


def _http_sidecar_route_rule_payload(rule) -> dict[str, object]:
    payload: dict[str, object] = {"path_template": rule.path_template}
    if rule.method is not None:
        payload = {"method": rule.method, **payload}
    if rule.static_tree:
        payload["static_tree"] = True
    return payload


def _visibility_payload(parsed: ParsedAppContract) -> dict[str, object]:
    payload: dict[str, object] = {"platform_roles": parsed.contract.visibility.platform_roles}
    if parsed.contract.visibility.workspace_roles is not None:
        payload["workspace_roles"] = parsed.contract.visibility.workspace_roles
    if parsed.contract.visibility.capabilities is not None:
        payload["capabilities"] = parsed.contract.visibility.capabilities
    return payload


def _hook_timeouts_payload(parsed: ParsedAppContract) -> dict[str, int]:
    timeouts = parsed.contract.hook_timeouts
    payload = {
        "install_seconds": timeouts.install_seconds,
        "upgrade_seconds": timeouts.upgrade_seconds,
        "migrate_seconds": timeouts.migrate_seconds,
        "export_seconds": timeouts.export_seconds,
        "import_seconds": timeouts.import_seconds,
        "validate_after_import_seconds": timeouts.validate_after_import_seconds,
        "repair_after_import_seconds": timeouts.repair_after_import_seconds,
        "health_check_seconds": timeouts.health_check_seconds,
    }
    if timeouts.backend_seconds != 30:
        payload = {"backend_seconds": timeouts.backend_seconds, **payload}
    return payload


def write_app_contract_file(source_root: Path, parsed: ParsedAppContract) -> Path:
    """Write one canonical app contract file into the given app root."""
    source_root.mkdir(parents=True, exist_ok=True)
    contract_file = app_contract_path(source_root)
    contract_file.write_text(json.dumps(app_contract_payload(parsed), indent=2) + "\n", encoding="utf-8")
    return contract_file
