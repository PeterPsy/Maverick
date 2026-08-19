"""Permissions section parsing for app contracts."""

from __future__ import annotations

from core.apps.contract_validation import (
    _expect_bool,
    _expect_mapping,
    _expect_network_target_list,
    _expect_permission_name_list,
    _expect_string,
    _reject_unexpected_fields,
)
from core.apps.errors import AppContractValidationError
from core.apps.models import (
    AppHostPermissionDeclaration,
    AppNetworkPermissionDeclaration,
    AppPermissionsDeclaration,
    AppProviderPermissionDeclaration,
    AppRuntimePermissionDeclaration,
    AppSecretPermissionDeclaration,
)


PROVIDER_CREDENTIAL_SOURCES = {"none", "core-vault"}


def parse_permissions_section(payload: dict[str, object]) -> AppPermissionsDeclaration:
    _reject_unexpected_fields(payload, {"secrets", "network", "runtime", "host", "providers"}, label="permissions")
    secrets_payload = _expect_mapping(payload.get("secrets", {}), label="permissions.secrets")
    network_payload = _expect_mapping(payload.get("network", {}), label="permissions.network")
    runtime_payload = _expect_mapping(payload.get("runtime", {}), label="permissions.runtime")
    host_payload = _expect_mapping(payload.get("host", {}), label="permissions.host")
    providers_payload = _expect_mapping(payload.get("providers", {}), label="permissions.providers")
    _reject_unexpected_fields(secrets_payload, {"read", "write"}, label="permissions.secrets")
    _reject_unexpected_fields(network_payload, {"outbound"}, label="permissions.network")
    _reject_unexpected_fields(
        runtime_payload,
        {"create_sessions", "cleanup_sessions", "receive_cleanup_callbacks"},
        label="permissions.runtime",
    )
    _reject_unexpected_fields(host_payload, {"telemetry"}, label="permissions.host")
    _reject_unexpected_fields(
        providers_payload,
        {"model_proxy", "credential_source", "deliver_secrets_to_app"},
        label="permissions.providers",
    )
    credential_source = (
        _expect_string(providers_payload, "credential_source")
        if "credential_source" in providers_payload
        else "none"
    )
    if credential_source not in PROVIDER_CREDENTIAL_SOURCES:
        allowed = ", ".join(sorted(PROVIDER_CREDENTIAL_SOURCES))
        raise AppContractValidationError(f"`permissions.providers.credential_source` must be one of {allowed}.")
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
            receive_cleanup_callbacks=_expect_bool(
                runtime_payload,
                "receive_cleanup_callbacks",
                default=False,
            ),
        ),
        host=AppHostPermissionDeclaration(telemetry=_expect_bool(host_payload, "telemetry", default=False)),
        providers=AppProviderPermissionDeclaration(
            model_proxy=_expect_bool(providers_payload, "model_proxy", default=False),
            credential_source=credential_source,
            deliver_secrets_to_app=_expect_bool(providers_payload, "deliver_secrets_to_app", default=False),
        ),
    )
