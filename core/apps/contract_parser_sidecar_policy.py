"""Confinement and browser-origin parsing for app-owned HTTP sidecars."""

from __future__ import annotations

import re
from typing import Any

from core.apps.contract_validation import (
    _expect_bool,
    _expect_mapping,
    _expect_string,
    _expect_string_list,
    _reject_unexpected_fields,
)
from core.apps.errors import AppContractValidationError
from core.apps.models import (
    HttpSidecarBrowserOriginSpec,
    HttpSidecarProcessPolicy,
    HttpSidecarResourceLimits,
)


_SANDBOX_SUBSTITUTIONS = {
    "${app.data_dir}",
    "${app.source_dir}",
    "${service.port}",
    "${service.token}",
}
_SUBSTITUTION_PATTERN = re.compile(r"\$\{[^{}]+\}")
_FORBIDDEN_ENV_NAMES = {
    "ANTHROPIC_API_KEY",
    "AZURE_OPENAI_API_KEY",
    "CODEX_HOME",
    "COOKIE",
    "CLAUDE_CODE_OAUTH_TOKEN",
    "GH_TOKEN",
    "GITHUB_TOKEN",
    "GOOGLE_APPLICATION_CREDENTIALS",
    "HOME",
    "MAVERICK_API_TOKEN",
    "MAVERICK_BOOTSTRAP_SECRET",
    "MAVERICK_RUNTIME_API_SECRET",
    "MAVERICK_RUNTIME_API_TOKEN",
    "MAVERICK_SECRET_STORE_KEY",
    "OPENAI_API_KEY",
    "VAULT_TOKEN",
}
_DEFAULT_MEMORY_BYTES = 4 * 1024 * 1024 * 1024
_DEFAULT_OPEN_FILES = 1024
_DEFAULT_REQUEST_CONCURRENCY = 32


def parse_process_policy(payload: dict[str, Any], *, label: str) -> HttpSidecarProcessPolicy:
    """Parse the fail-closed process and network confinement declaration."""
    policy_label = f"{label}.process_policy"
    _reject_unexpected_fields(
        payload,
        {
            "inherit_host_env",
            "sandbox",
            "bundle_read_only",
            "workspace_data_write",
            "network",
            "transport",
            "outbound",
            "limits",
        },
        label=policy_label,
    )
    inherit_host_env = _expect_bool(payload, "inherit_host_env")
    if inherit_host_env:
        raise AppContractValidationError(f"`{policy_label}.inherit_host_env` must be false.")
    sandbox = _expect_string(payload, "sandbox")
    if sandbox != "required":
        raise AppContractValidationError(f"`{policy_label}.sandbox` must be `required`.")
    bundle_read_only = _expect_bool(payload, "bundle_read_only")
    if not bundle_read_only:
        raise AppContractValidationError(f"`{policy_label}.bundle_read_only` must be true.")
    workspace_data_write = _expect_bool(payload, "workspace_data_write")
    if not workspace_data_write:
        raise AppContractValidationError(f"`{policy_label}.workspace_data_write` must be true.")
    network = _expect_string(payload, "network")
    if network != "isolated":
        raise AppContractValidationError(f"`{policy_label}.network` must be `isolated`.")
    transport = _expect_string(payload, "transport")
    if transport != "unix_relay":
        raise AppContractValidationError(f"`{policy_label}.transport` must be `unix_relay`.")
    outbound = _expect_string_list(payload, "outbound")
    if outbound:
        raise AppContractValidationError(f"`{policy_label}.outbound` must be empty for isolated sidecars.")
    limits_payload = _expect_mapping(payload.get("limits", {}), label=f"{policy_label}.limits")
    _reject_unexpected_fields(
        limits_payload,
        {"memory_bytes", "open_files", "request_concurrency"},
        label=f"{policy_label}.limits",
    )
    limits = HttpSidecarResourceLimits(
        memory_bytes=_expect_bounded_int(
            limits_payload,
            "memory_bytes",
            default=_DEFAULT_MEMORY_BYTES,
            minimum=64 * 1024 * 1024,
            maximum=64 * 1024 * 1024 * 1024,
            label=f"{policy_label}.limits.memory_bytes",
        ),
        open_files=_expect_bounded_int(
            limits_payload,
            "open_files",
            default=_DEFAULT_OPEN_FILES,
            minimum=64,
            maximum=65536,
            label=f"{policy_label}.limits.open_files",
        ),
        request_concurrency=_expect_bounded_int(
            limits_payload,
            "request_concurrency",
            default=_DEFAULT_REQUEST_CONCURRENCY,
            minimum=1,
            maximum=1024,
            label=f"{policy_label}.limits.request_concurrency",
        ),
    )
    return HttpSidecarProcessPolicy(
        inherit_host_env=inherit_host_env,
        sandbox="required",
        bundle_read_only=bundle_read_only,
        workspace_data_write=workspace_data_write,
        network="isolated",
        transport="unix_relay",
        outbound=outbound,
        limits=limits,
    )


def parse_browser_origin(payload: dict[str, Any], *, label: str) -> HttpSidecarBrowserOriginSpec:
    """Parse the isolated browser-origin policy."""
    origin_label = f"{label}.browser_origin"
    _reject_unexpected_fields(
        payload,
        {"mode", "csp_profile", "frame_ancestors", "connect_src", "immutable_asset_prefixes"},
        label=origin_label,
    )
    mode = _expect_string(payload, "mode")
    if mode != "isolated":
        raise AppContractValidationError(f"`{origin_label}.mode` must be `isolated`.")
    csp_profile = _expect_string(payload, "csp_profile")
    if csp_profile != "self_hosted_web_app":
        raise AppContractValidationError(f"`{origin_label}.csp_profile` must be `self_hosted_web_app`.")
    frame_ancestors = _expect_string_list(payload, "frame_ancestors")
    if frame_ancestors != ["platform"]:
        raise AppContractValidationError(f"`{origin_label}.frame_ancestors` must be [`platform`].")
    connect_src = _expect_string_list(payload, "connect_src")
    if connect_src != ["self"]:
        raise AppContractValidationError(f"`{origin_label}.connect_src` must be [`self`].")
    immutable_asset_prefixes = (
        _expect_string_list(payload, "immutable_asset_prefixes")
        if "immutable_asset_prefixes" in payload
        else []
    )
    if len(immutable_asset_prefixes) > 8:
        raise AppContractValidationError(f"`{origin_label}.immutable_asset_prefixes` may contain at most 8 values.")
    for prefix in immutable_asset_prefixes:
        if not _valid_immutable_asset_prefix(prefix):
            raise AppContractValidationError(
                f"`{origin_label}.immutable_asset_prefixes` values must be canonical non-API absolute directory prefixes."
            )
    if len(set(immutable_asset_prefixes)) != len(immutable_asset_prefixes):
        raise AppContractValidationError(f"`{origin_label}.immutable_asset_prefixes` must not contain duplicates.")
    return HttpSidecarBrowserOriginSpec(
        mode="isolated",
        csp_profile="self_hosted_web_app",
        frame_ancestors=frame_ancestors,
        connect_src=connect_src,
        immutable_asset_prefixes=immutable_asset_prefixes,
    )


def _valid_immutable_asset_prefix(value: str) -> bool:
    if not value.startswith("/") or value == "/" or not value.endswith("/"):
        return False
    if value.startswith("/api/") or value.startswith("/.well-known/"):
        return False
    if "//" in value or "\\" in value or "%" in value or "?" in value or "#" in value:
        return False
    return all(segment not in {"", ".", ".."} for segment in value[1:-1].split("/"))


def parse_sidecar_env(
    payload: dict[str, Any],
    *,
    sandbox_required: bool,
    artifact_ids: set[str] | None = None,
    label: str,
) -> dict[str, str]:
    """Parse an explicit sidecar environment without host-secret inheritance."""
    result: dict[str, str] = {}
    for key, value in payload.items():
        if not isinstance(key, str) or not key.strip():
            raise AppContractValidationError(f"`{label}.env` keys must be non-empty strings.")
        if not isinstance(value, str):
            raise AppContractValidationError(f"`{label}.env.{key}` must be a string.")
        normalized_key = key.strip()
        if sandbox_required and _is_forbidden_sandbox_env_name(normalized_key):
            raise AppContractValidationError(f"`{label}.env.{normalized_key}` is forbidden for sandbox-required sidecars.")
        substitutions = set(_SUBSTITUTION_PATTERN.findall(value))
        allowed_substitutions = _SANDBOX_SUBSTITUTIONS | {
            f"${{artifact.{artifact_id}}}"
            for artifact_id in (artifact_ids or set())
        }
        if sandbox_required and not substitutions.issubset(allowed_substitutions):
            raise AppContractValidationError(
                f"`{label}.env.{normalized_key}` contains a substitution unavailable to sandbox-required sidecars."
            )
        result[normalized_key] = value
    return result


def _expect_bounded_int(
    payload: dict[str, Any],
    key: str,
    *,
    default: int,
    minimum: int,
    maximum: int,
    label: str,
) -> int:
    value = payload.get(key, default)
    if isinstance(value, bool) or not isinstance(value, int) or not minimum <= value <= maximum:
        raise AppContractValidationError(f"`{label}` must be an integer from {minimum} through {maximum}.")
    return value


def _is_forbidden_sandbox_env_name(name: str) -> bool:
    upper = name.upper()
    return (
        upper in _FORBIDDEN_ENV_NAMES
        or upper.endswith("_API_KEY")
        or upper.endswith("_BOOTSTRAP_SECRET")
        or upper.endswith("_COOKIE")
        or upper.startswith("AWS_")
        or upper.startswith("AZURE_")
        or upper.startswith("GOOGLE_")
    )
