"""Parser for app-owned long-running service declarations."""

from __future__ import annotations

from pathlib import Path, PurePosixPath
import re
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
    HttpSidecarBrowserOriginSpec,
    HttpSidecarHealthSpec,
    HttpSidecarLogSpec,
    HttpSidecarProcessPolicy,
    HttpSidecarProxySpec,
    HttpSidecarResourceLimits,
    HttpSidecarRoutePolicy,
    HttpSidecarRouteRule,
    HttpSidecarSpec,
)
from core.apps.sidecar_route_policy import validate_route_template


_ALLOWED_SERVICE_RUNTIMES = {"python", "node", "generic"}
_ALLOWED_HTTP_METHODS = {"GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"}
_LOOPBACK_HOSTS = {"127.0.0.1", "localhost", "::1"}
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
            "browser_origin",
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
    process_policy = _parse_process_policy(
        _expect_mapping(process_policy_payload, label=f"{label}.process_policy"),
        label=label,
    )
    browser_origin_payload = payload.get("browser_origin")
    browser_origin = (
        _parse_browser_origin(
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
        env=_parse_env(
            _expect_mapping(payload.get("env", {}), label=f"{label}.env"),
            sandbox_required=process_policy.sandbox == "required",
            label=label,
        ),
        process_policy=process_policy,
        browser_origin=browser_origin,
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
        route_policy=_parse_route_policy(
            _expect_mapping(payload.get("route_policy", {}), label=f"{label}.proxy.route_policy"),
            label=label,
        ),
    )


def _parse_route_policy(payload: dict[str, Any], *, label: str) -> HttpSidecarRoutePolicy:
    _reject_unexpected_fields(payload, {"pass_through", "handled_by_core", "blocked"}, label=f"{label}.proxy.route_policy")
    return HttpSidecarRoutePolicy(
        pass_through=_parse_route_rules(
            payload.get("pass_through", []),
            label=f"{label}.proxy.route_policy.pass_through",
            require_method=True,
        ),
        handled_by_core=_parse_route_rules(
            payload.get("handled_by_core", []),
            label=f"{label}.proxy.route_policy.handled_by_core",
            require_method=True,
        ),
        blocked=_parse_route_rules(
            payload.get("blocked", []),
            label=f"{label}.proxy.route_policy.blocked",
            require_method=False,
        ),
    )


def _parse_route_rules(payload: Any, *, label: str, require_method: bool) -> list[HttpSidecarRouteRule]:
    if not isinstance(payload, list):
        raise AppContractValidationError(f"`{label}` must be a list.")
    rules: list[HttpSidecarRouteRule] = []
    for index, item in enumerate(payload):
        rule = _expect_mapping(item, label=f"{label}[{index}]")
        rule_label = f"{label}[{index}]"
        _reject_unexpected_fields(rule, {"method", "path_template", "static_tree"}, label=rule_label)
        method = rule.get("method")
        normalized_method = None
        if method is not None:
            if not isinstance(method, str) or not method.strip():
                raise AppContractValidationError(f"`{label}[{index}].method` must be a non-empty string when provided.")
            normalized_method = method.strip().upper()
            if normalized_method not in _ALLOWED_HTTP_METHODS:
                raise AppContractValidationError(f"`{label}[{index}].method` is not a supported HTTP method.")
        if require_method and normalized_method is None:
            raise AppContractValidationError(f"`{rule_label}.method` is required for authorized sidecar routes.")
        static_tree = _expect_bool(rule, "static_tree", default=False)
        path_template = _expect_string(rule, "path_template")
        try:
            path_template = validate_route_template(path_template, static_tree=static_tree)
        except ValueError as error:
            raise AppContractValidationError(f"`{rule_label}.path_template` {error}.") from error
        if static_tree and normalized_method not in {"GET", "HEAD"}:
            raise AppContractValidationError(f"`{rule_label}.static_tree` requires GET or HEAD.")
        rules.append(
            HttpSidecarRouteRule(
                method=normalized_method,
                path_template=path_template,
                static_tree=static_tree,
            )
        )
    return rules


def _parse_logs(payload: dict[str, Any], *, app_id: str, label: str) -> HttpSidecarLogSpec:
    _reject_unexpected_fields(payload, {"stdout", "stderr"}, label=f"{label}.logs")
    return HttpSidecarLogSpec(
        stdout=_expect_workspace_log_path(payload, "stdout", app_id=app_id, label=f"{label}.logs.stdout"),
        stderr=_expect_workspace_log_path(payload, "stderr", app_id=app_id, label=f"{label}.logs.stderr"),
    )


def _parse_process_policy(payload: dict[str, Any], *, label: str) -> HttpSidecarProcessPolicy:
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


def _parse_browser_origin(payload: dict[str, Any], *, label: str) -> HttpSidecarBrowserOriginSpec:
    origin_label = f"{label}.browser_origin"
    _reject_unexpected_fields(
        payload,
        {"mode", "csp_profile", "frame_ancestors", "connect_src"},
        label=origin_label,
    )
    mode = _expect_string(payload, "mode")
    if mode != "isolated":
        raise AppContractValidationError(f"`{origin_label}.mode` must be `isolated`.")
    csp_profile = _expect_string(payload, "csp_profile")
    if csp_profile != "self_hosted_web_app":
        raise AppContractValidationError(
            f"`{origin_label}.csp_profile` must be `self_hosted_web_app`."
        )
    frame_ancestors = _expect_string_list(payload, "frame_ancestors")
    if frame_ancestors != ["platform"]:
        raise AppContractValidationError(f"`{origin_label}.frame_ancestors` must be [`platform`].")
    connect_src = _expect_string_list(payload, "connect_src")
    if connect_src != ["self"]:
        raise AppContractValidationError(f"`{origin_label}.connect_src` must be [`self`].")
    return HttpSidecarBrowserOriginSpec(
        mode="isolated",
        csp_profile="self_hosted_web_app",
        frame_ancestors=frame_ancestors,
        connect_src=connect_src,
    )


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


def _parse_env(payload: dict[str, Any], *, sandbox_required: bool, label: str) -> dict[str, str]:
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
        if sandbox_required and not substitutions.issubset(_SANDBOX_SUBSTITUTIONS):
            raise AppContractValidationError(
                f"`{label}.env.{normalized_key}` contains a substitution unavailable to sandbox-required sidecars."
            )
        result[normalized_key] = value
    return result


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
