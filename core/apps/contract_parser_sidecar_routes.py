"""Route and entrypoint-access parsing for app-owned HTTP sidecars."""

from __future__ import annotations

from typing import Any

from core.apps.contract_validation import (
    _expect_bool,
    _expect_mapping,
    _expect_string,
    _reject_unexpected_fields,
)
from core.apps.errors import AppContractValidationError
from core.apps.models import (
    HttpSidecarEntrypointAccessSpec,
    HttpSidecarEntrypointSurfaceSpec,
    HttpSidecarProxySpec,
    HttpSidecarRoutePolicy,
    HttpSidecarRouteRule,
)
from core.apps.sidecar_route_policy import validate_route_template


_ALLOWED_HTTP_METHODS = {"GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"}
_ENTRYPOINT_SURFACES = {"backend", "cli", "mcp", "reference"}


def parse_entrypoint_access(
    payload: dict[str, Any],
    *,
    proxy: HttpSidecarProxySpec | None,
    label: str,
) -> HttpSidecarEntrypointAccessSpec:
    """Parse a bounded, invocation-local sidecar capability declaration."""
    access_label = f"{label}.entrypoint_access"
    _reject_unexpected_fields(
        payload,
        {
            "ttl_seconds",
            "request_budget",
            "max_request_body_bytes",
            "max_response_body_bytes",
            "streaming",
            "surfaces",
        },
        label=access_label,
    )
    if proxy is None:
        raise AppContractValidationError(f"`{access_label}` requires a governed sidecar proxy.")
    ttl_seconds = _expect_required_bounded_int(
        payload, "ttl_seconds", minimum=1, maximum=30, label=access_label
    )
    request_budget = _expect_required_bounded_int(
        payload, "request_budget", minimum=1, maximum=256, label=access_label
    )
    max_request_body_bytes = _expect_required_bounded_int(
        payload,
        "max_request_body_bytes",
        minimum=0,
        maximum=16 * 1024 * 1024,
        label=access_label,
    )
    max_response_body_bytes = _expect_required_bounded_int(
        payload,
        "max_response_body_bytes",
        minimum=1,
        maximum=64 * 1024 * 1024,
        label=access_label,
    )
    if "streaming" not in payload:
        raise AppContractValidationError(f"`{access_label}.streaming` is required.")
    if _expect_bool(payload, "streaming"):
        raise AppContractValidationError(
            f"`{access_label}.streaming` must be false; long-lived streams require a distinct job capability."
        )
    raw_surfaces = payload.get("surfaces")
    if not isinstance(raw_surfaces, list) or not raw_surfaces:
        raise AppContractValidationError(f"`{access_label}.surfaces` must be a non-empty list.")

    surfaces: list[HttpSidecarEntrypointSurfaceSpec] = []
    seen: set[str] = set()
    pass_through = {
        (rule.method, rule.path_template, rule.static_tree)
        for rule in proxy.route_policy.pass_through
    }
    for index, raw_surface in enumerate(raw_surfaces):
        surface_label = f"{access_label}.surfaces[{index}]"
        surface_payload = _expect_mapping(raw_surface, label=surface_label)
        _reject_unexpected_fields(surface_payload, {"surface", "routes"}, label=surface_label)
        surface = _expect_string(surface_payload, "surface")
        if surface not in _ENTRYPOINT_SURFACES:
            raise AppContractValidationError(
                f"`{surface_label}.surface` must be one of backend, cli, mcp, or reference."
            )
        if surface in seen:
            raise AppContractValidationError(f"Duplicate entrypoint access surface `{surface}`.")
        seen.add(surface)
        routes = parse_route_rules(
            surface_payload.get("routes"),
            label=f"{surface_label}.routes",
            require_method=True,
        )
        if not routes:
            raise AppContractValidationError(f"`{surface_label}.routes` must not be empty.")
        for route in routes:
            if route.static_tree:
                raise AppContractValidationError(
                    f"`{surface_label}.routes` cannot grant static subtrees to an app entrypoint."
                )
            if surface == "reference" and route.method not in {"GET", "HEAD"}:
                raise AppContractValidationError(
                    f"`{surface_label}.routes` may grant only GET or HEAD to reference entrypoints."
                )
            if (route.method, route.path_template, route.static_tree) not in pass_through:
                raise AppContractValidationError(
                    f"`{surface_label}.routes` must be an exact subset of proxy pass_through routes."
                )
        surfaces.append(
            HttpSidecarEntrypointSurfaceSpec(
                surface=surface,  # type: ignore[arg-type]
                routes=routes,
            )
        )
    return HttpSidecarEntrypointAccessSpec(
        ttl_seconds=ttl_seconds,
        request_budget=request_budget,
        max_request_body_bytes=max_request_body_bytes,
        max_response_body_bytes=max_response_body_bytes,
        streaming=False,
        surfaces=surfaces,
    )


def parse_route_policy(payload: dict[str, Any], *, label: str) -> HttpSidecarRoutePolicy:
    """Parse the disjoint governed route-policy lists."""
    _reject_unexpected_fields(
        payload,
        {"pass_through", "handled_by_core", "blocked"},
        label=f"{label}.proxy.route_policy",
    )
    return HttpSidecarRoutePolicy(
        pass_through=parse_route_rules(
            payload.get("pass_through", []),
            label=f"{label}.proxy.route_policy.pass_through",
            require_method=True,
        ),
        handled_by_core=parse_route_rules(
            payload.get("handled_by_core", []),
            label=f"{label}.proxy.route_policy.handled_by_core",
            require_method=True,
        ),
        blocked=parse_route_rules(
            payload.get("blocked", []),
            label=f"{label}.proxy.route_policy.blocked",
            require_method=False,
        ),
    )


def parse_route_rules(payload: Any, *, label: str, require_method: bool) -> list[HttpSidecarRouteRule]:
    """Parse canonical exact or static-tree sidecar route rules."""
    if not isinstance(payload, list):
        raise AppContractValidationError(f"`{label}` must be a list.")
    rules: list[HttpSidecarRouteRule] = []
    for index, item in enumerate(payload):
        rule_label = f"{label}[{index}]"
        rule = _expect_mapping(item, label=rule_label)
        _reject_unexpected_fields(rule, {"method", "path_template", "static_tree"}, label=rule_label)
        method = rule.get("method")
        normalized_method = None
        if method is not None:
            if not isinstance(method, str) or not method.strip():
                raise AppContractValidationError(
                    f"`{rule_label}.method` must be a non-empty string when provided."
                )
            normalized_method = method.strip().upper()
            if normalized_method not in _ALLOWED_HTTP_METHODS:
                raise AppContractValidationError(f"`{rule_label}.method` is not a supported HTTP method.")
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


def _expect_required_bounded_int(
    payload: dict[str, Any],
    key: str,
    *,
    minimum: int,
    maximum: int,
    label: str,
) -> int:
    if key not in payload:
        raise AppContractValidationError(f"`{label}.{key}` is required.")
    value = payload[key]
    if isinstance(value, bool) or not isinstance(value, int) or not minimum <= value <= maximum:
        raise AppContractValidationError(
            f"`{label}.{key}` must be an integer from {minimum} through {maximum}."
        )
    return value
