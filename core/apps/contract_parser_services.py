"""Parser for app-owned long-running service declarations."""

from __future__ import annotations

from pathlib import Path, PurePosixPath
from typing import Any

from core.apps.contract_validation import (
    _expect_bool,
    _expect_mapping,
    _expect_relative_contract_path,
    _expect_string,
    _expect_string_list,
    _expect_slug,
    _expect_timeout,
    _reject_unexpected_fields,
)
from core.apps.errors import AppContractValidationError
from core.apps.models import (
    AppServicesDeclaration,
    HttpSidecarBindSpec,
    HttpSidecarHealthSpec,
    HttpSidecarLogSpec,
    HttpSidecarProxySpec,
    HttpSidecarSpec,
)
from core.apps.contract_parser_sidecar_artifacts import (
    parse_sidecar_artifact_mounts,
    parse_sidecar_diagnostics,
    parse_sidecar_prewarm,
)
from core.apps.contract_parser_sidecar_policy import (
    parse_browser_origin,
    parse_process_policy,
    parse_sidecar_env,
)
from core.apps.contract_parser_sidecar_routes import (
    parse_entrypoint_access,
    parse_route_policy,
)


_ALLOWED_SERVICE_RUNTIMES = {"python", "node", "generic"}
_LOOPBACK_HOSTS = {"127.0.0.1", "localhost", "::1"}


def parse_services_section(
    source_root: Path,
    payload: dict[str, Any],
    *,
    app_id: str,
    supported_workspace_modes: list[str] | None,
) -> AppServicesDeclaration:
    """Parse and validate the app-owned service section."""
    _reject_unexpected_fields(payload, {"http_sidecars"}, label="services")
    sidecars_payload = payload.get("http_sidecars", [])
    if not isinstance(sidecars_payload, list):
        raise AppContractValidationError("`services.http_sidecars` must be a list.")
    sidecars: list[HttpSidecarSpec] = []
    seen_ids: set[str] = set()
    sandbox_compatible = not supported_workspace_modes or "sandbox" in supported_workspace_modes
    for index, item in enumerate(sidecars_payload):
        sidecar = _parse_http_sidecar(
            source_root,
            _expect_mapping(item, label=f"services.http_sidecars[{index}]"),
            app_id=app_id,
            sandbox_compatible=sandbox_compatible,
            label=f"services.http_sidecars[{index}]",
        )
        if sidecar.service_id in seen_ids:
            raise AppContractValidationError(f"Duplicate HTTP sidecar id `{sidecar.service_id}`.")
        seen_ids.add(sidecar.service_id)
        sidecars.append(sidecar)
    return AppServicesDeclaration(http_sidecars=sidecars)


def _parse_http_sidecar(
    source_root: Path,
    payload: dict[str, Any],
    *,
    app_id: str,
    sandbox_compatible: bool,
    label: str,
) -> HttpSidecarSpec:
    _reject_unexpected_fields(
        payload,
        {
            "id",
            "runtime",
            "package_manager",
            "working_directory",
            "command",
            "env",
            "process_policy",
            "artifact_mounts",
            "prewarm",
            "diagnostics",
            "browser_origin",
            "entrypoint_access",
            "bind",
            "health",
            "proxy",
            "logs",
        },
        label=label,
    )
    service_id = _expect_slug(payload, "id")
    runtime = _expect_string(payload, "runtime")
    if runtime not in _ALLOWED_SERVICE_RUNTIMES:
        raise AppContractValidationError(f"`{label}.runtime` must be one of python, node, or generic.")
    command = _expect_string_list(payload, "command")
    if not command:
        raise AppContractValidationError(f"`{label}.command` must include at least one argument.")
    working_directory = _expect_relative_contract_path(
        source_root,
        str(payload.get("working_directory") or "."),
        label=f"{label}.working_directory",
        allow_directory=True,
    )
    package_manager = payload.get("package_manager")
    if package_manager is not None and (not isinstance(package_manager, str) or not package_manager.strip()):
        raise AppContractValidationError(f"`{label}.package_manager` must be a non-empty string when provided.")
    process_policy_payload = payload.get("process_policy")
    if process_policy_payload is None:
        raise AppContractValidationError(f"`{label}.process_policy` is required for HTTP sidecars.")
    process_policy = parse_process_policy(
        _expect_mapping(process_policy_payload, label=f"{label}.process_policy"),
        label=label,
    )
    artifact_mounts = parse_sidecar_artifact_mounts(payload.get("artifact_mounts", []), label=label)
    prewarm_payload = payload.get("prewarm")
    prewarm = (
        parse_sidecar_prewarm(_expect_mapping(prewarm_payload, label=f"{label}.prewarm"), label=label)
        if prewarm_payload is not None
        else None
    )
    diagnostics_payload = payload.get("diagnostics")
    diagnostics = (
        parse_sidecar_diagnostics(_expect_mapping(diagnostics_payload, label=f"{label}.diagnostics"), label=label)
        if diagnostics_payload is not None
        else None
    )
    browser_origin_payload = payload.get("browser_origin")
    browser_origin = (
        parse_browser_origin(
            _expect_mapping(browser_origin_payload, label=f"{label}.browser_origin"),
            label=label,
        )
        if browser_origin_payload is not None
        else None
    )
    bind = _parse_bind(_expect_mapping(payload.get("bind", {}), label=f"{label}.bind"), sandbox_compatible=sandbox_compatible, label=label)
    health = _parse_health(_expect_mapping(payload.get("health", {}), label=f"{label}.health"), label=label)
    proxy_payload = payload.get("proxy")
    proxy = None
    if proxy_payload is not None:
        proxy = _parse_proxy(_expect_mapping(proxy_payload, label=f"{label}.proxy"), sandbox_compatible=sandbox_compatible, label=label)
    entrypoint_access_payload = payload.get("entrypoint_access")
    entrypoint_access = (
        parse_entrypoint_access(
            _expect_mapping(entrypoint_access_payload, label=f"{label}.entrypoint_access"),
            proxy=proxy,
            label=label,
        )
        if entrypoint_access_payload is not None
        else None
    )
    logs_payload = payload.get("logs")
    logs = None
    if logs_payload is not None:
        logs = _parse_logs(_expect_mapping(logs_payload, label=f"{label}.logs"), app_id=app_id, label=label)
    return HttpSidecarSpec(
        service_id=service_id,
        runtime=runtime,  # type: ignore[arg-type]
        package_manager=package_manager.strip() if isinstance(package_manager, str) else None,
        working_directory=working_directory,
        command=command,
        env=parse_sidecar_env(
            _expect_mapping(payload.get("env", {}), label=f"{label}.env"),
            sandbox_required=process_policy.sandbox == "required",
            artifact_ids={mount.artifact_id for mount in artifact_mounts},
            label=label,
        ),
        process_policy=process_policy,
        artifact_mounts=artifact_mounts,
        prewarm=prewarm,
        diagnostics=diagnostics,
        browser_origin=browser_origin,
        entrypoint_access=entrypoint_access,
        bind=bind,
        health=health,
        proxy=proxy,
        logs=logs,
    )


def _parse_bind(payload: dict[str, Any], *, sandbox_compatible: bool, label: str) -> HttpSidecarBindSpec:
    _reject_unexpected_fields(payload, {"host", "port"}, label=f"{label}.bind")
    host = _expect_string(payload, "host")
    if sandbox_compatible and host not in _LOOPBACK_HOSTS:
        raise AppContractValidationError(f"`{label}.bind.host` must be loopback for sandbox-compatible apps.")
    raw_port = payload.get("port")
    if raw_port == "auto":
        port: int | str = "auto"
    elif isinstance(raw_port, int) and 0 < raw_port <= 65535:
        port = raw_port
    else:
        raise AppContractValidationError(f"`{label}.bind.port` must be `auto` or a TCP port from 1 to 65535.")
    return HttpSidecarBindSpec(host=host, port=port)  # type: ignore[arg-type]


def _parse_health(payload: dict[str, Any], *, label: str) -> HttpSidecarHealthSpec:
    _reject_unexpected_fields(payload, {"path", "timeout_ms"}, label=f"{label}.health")
    path = _expect_http_path_prefix(payload, "path", label=f"{label}.health.path")
    timeout_ms = _expect_timeout(payload, "timeout_ms", default=30000)
    return HttpSidecarHealthSpec(path=path, timeout_ms=timeout_ms)


def _parse_proxy(payload: dict[str, Any], *, sandbox_compatible: bool, label: str) -> HttpSidecarProxySpec:
    _reject_unexpected_fields(payload, {"mount", "streaming", "sse", "websocket", "route_policy"}, label=f"{label}.proxy")
    if "route_policy" not in payload:
        raise AppContractValidationError(f"`{label}.proxy.route_policy` is required for exposed HTTP sidecars.")
    websocket = _expect_bool(payload, "websocket", default=False)
    if sandbox_compatible and websocket:
        raise AppContractValidationError(f"`{label}.proxy.websocket` is not allowed for sandbox-compatible sidecars.")
    return HttpSidecarProxySpec(
        mount=_expect_http_path_prefix(payload, "mount", label=f"{label}.proxy.mount"),
        streaming=_expect_bool(payload, "streaming", default=False),
        sse=_expect_bool(payload, "sse", default=False),
        websocket=websocket,
        route_policy=parse_route_policy(
            _expect_mapping(payload.get("route_policy", {}), label=f"{label}.proxy.route_policy"),
            label=label,
        ),
    )


def _parse_logs(payload: dict[str, Any], *, app_id: str, label: str) -> HttpSidecarLogSpec:
    _reject_unexpected_fields(payload, {"stdout", "stderr"}, label=f"{label}.logs")
    return HttpSidecarLogSpec(
        stdout=_expect_workspace_log_path(payload, "stdout", app_id=app_id, label=f"{label}.logs.stdout"),
        stderr=_expect_workspace_log_path(payload, "stderr", app_id=app_id, label=f"{label}.logs.stderr"),
    )


def _expect_http_path_prefix(payload: dict[str, Any], key: str, *, label: str) -> str:
    value = _expect_string(payload, key)
    if not value.startswith("/") or "\\" in value or "?" in value or "#" in value:
        raise AppContractValidationError(f"`{label}` must be an absolute HTTP path without query or fragment.")
    if "/../" in value or value.endswith("/.."):
        raise AppContractValidationError(f"`{label}` must not contain path traversal.")
    return value.rstrip("/") or "/"


def _expect_workspace_log_path(payload: dict[str, Any], key: str, *, app_id: str, label: str) -> str:
    value = _expect_string(payload, key)
    path = PurePosixPath(value)
    if path.is_absolute() or ".." in path.parts:
        raise AppContractValidationError(f"`{label}` must be a relative workspace log path.")
    prefix = PurePosixPath("logs") / "apps" / app_id
    if not path.parts[: len(prefix.parts)] == prefix.parts or len(path.parts) <= len(prefix.parts):
        raise AppContractValidationError(f"`{label}` must stay under `logs/apps/{app_id}/`.")
    return path.as_posix()
