"""Permissions section parsing for app contracts."""

from __future__ import annotations

from core.apps.contract_validation import (
    _expect_bool,
    _expect_mapping,
    _expect_network_target_list,
    _expect_permission_name_list,
    _reject_unexpected_fields,
)
from core.apps.models import (
    AppHostPermissionDeclaration,
    AppNetworkPermissionDeclaration,
    AppPermissionsDeclaration,
    AppRuntimePermissionDeclaration,
    AppSecretPermissionDeclaration,
)


def parse_permissions_section(payload: dict[str, object]) -> AppPermissionsDeclaration:
    _reject_unexpected_fields(payload, {"secrets", "network", "runtime", "host"}, label="permissions")
    secrets_payload = _expect_mapping(payload.get("secrets", {}), label="permissions.secrets")
    network_payload = _expect_mapping(payload.get("network", {}), label="permissions.network")
    runtime_payload = _expect_mapping(payload.get("runtime", {}), label="permissions.runtime")
    host_payload = _expect_mapping(payload.get("host", {}), label="permissions.host")
    _reject_unexpected_fields(secrets_payload, {"read", "write"}, label="permissions.secrets")
    _reject_unexpected_fields(network_payload, {"outbound"}, label="permissions.network")
    _reject_unexpected_fields(runtime_payload, {"create_sessions", "cleanup_sessions"}, label="permissions.runtime")
    _reject_unexpected_fields(host_payload, {"telemetry"}, label="permissions.host")
    return AppPermissionsDeclaration(
        secrets=AppSecretPermissionDeclaration(
            read=_expect_permission_name_list(secrets_payload, "read", label="permissions.secrets"),
            write=_expect_permission_name_list(secrets_payload, "write", label="permissions.secrets"),
        ),
        network=AppNetworkPermissionDeclaration(
            outbound=_expect_network_target_list(network_payload, "outbound", label="permissions.network"),
        ),
        runtime=AppRuntimePermissionDeclaration(
            create_sessions=_expect_bool(runtime_payload, "create_sessions", default=False),
            cleanup_sessions=_expect_bool(runtime_payload, "cleanup_sessions", default=False),
        ),
        host=AppHostPermissionDeclaration(telemetry=_expect_bool(host_payload, "telemetry", default=False)),
    )
