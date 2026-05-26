"""Browser egress policy evaluation."""

from __future__ import annotations

import ipaddress
import socket
from urllib.parse import SplitResult, urlsplit, urlunsplit

from core.egress.models import (
    DEFAULT_BROWSER_EGRESS_POLICY,
    BrowserEgressPolicy,
    EgressDecision,
    EgressHop,
    EgressTarget,
)
from core.egress.networks import METADATA_HOSTS, restricted_address, restricted_host


def evaluate_browser_egress_url(
    url: str,
    *,
    policy: BrowserEgressPolicy = DEFAULT_BROWSER_EGRESS_POLICY,
    resolved_addresses: tuple[str, ...] | list[str] | None = None,
    allow_admin_dev_targets: bool = False,
) -> EgressDecision:
    """Evaluate one browser navigation URL against the core egress policy."""

    try:
        parsed = urlsplit(str(url).strip())
        parsed.port
    except ValueError:
        return EgressDecision(allowed=False, reason="blocked_invalid_port", url=str(url))

    scheme = parsed.scheme.lower()
    if scheme not in {item.lower() for item in policy.allowed_schemes}:
        return EgressDecision(allowed=False, reason="blocked_disallowed_scheme", url=str(url), scheme=scheme or None)

    host = _normalize_host(parsed.hostname)
    if not host:
        return EgressDecision(allowed=False, reason="blocked_missing_host", url=str(url), scheme=scheme)

    port = parsed.port or _default_port(scheme)
    normalized_url = _normalize_url(parsed, scheme=scheme, host=host, port=port)
    if _is_admin_dev_target(scheme=scheme, host=host, port=port, policy=policy):
        if allow_admin_dev_targets:
            return EgressDecision(
                allowed=True,
                reason="allowed_admin_dev_target",
                url=str(url),
                normalized_url=normalized_url,
                host=host,
                port=port,
                scheme=scheme,
            )
        return EgressDecision(
            allowed=False,
            reason="blocked_admin_dev_target_not_enabled",
            url=str(url),
            normalized_url=normalized_url,
            host=host,
            port=port,
            scheme=scheme,
        )

    if host in METADATA_HOSTS:
        return EgressDecision(
            allowed=False,
            reason="blocked_metadata_host",
            url=str(url),
            normalized_url=normalized_url,
            host=host,
            port=port,
            scheme=scheme,
        )

    blocked_host = restricted_host(host)
    if blocked_host:
        return EgressDecision(
            allowed=False,
            reason="blocked_restricted_host",
            url=str(url),
            normalized_url=normalized_url,
            host=host,
            port=port,
            scheme=scheme,
            blocked_address=blocked_host,
        )

    host_address = _parse_ip_address(host)
    if isinstance(host_address, ValueError):
        return EgressDecision(
            allowed=False,
            reason="blocked_invalid_ip_literal",
            url=str(url),
            normalized_url=normalized_url,
            host=host,
            port=port,
            scheme=scheme,
        )

    if host_address is not None:
        blocked_address = restricted_address(host_address)
        if blocked_address:
            return EgressDecision(
                allowed=False,
                reason="blocked_restricted_ip",
                url=str(url),
                normalized_url=normalized_url,
                host=host,
                port=port,
                scheme=scheme,
                blocked_address=blocked_address,
            )
        return EgressDecision(
            allowed=True,
            reason="allowed_public_http",
            url=str(url),
            normalized_url=normalized_url,
            host=host,
            port=port,
            scheme=scheme,
        )

    addresses = tuple(resolved_addresses or ())
    if policy.require_dns_resolution_for_hostnames and resolved_addresses is None:
        return EgressDecision(
            allowed=False,
            reason="blocked_dns_resolution_required",
            url=str(url),
            normalized_url=normalized_url,
            host=host,
            port=port,
            scheme=scheme,
        )
    if not addresses:
        return EgressDecision(
            allowed=False,
            reason="blocked_no_resolved_addresses",
            url=str(url),
            normalized_url=normalized_url,
            host=host,
            port=port,
            scheme=scheme,
        )

    for address in addresses:
        parsed_address = _parse_ip_address(address)
        if parsed_address is None or isinstance(parsed_address, ValueError):
            return EgressDecision(
                allowed=False,
                reason="blocked_invalid_ip_literal",
                url=str(url),
                normalized_url=normalized_url,
                host=host,
                port=port,
                scheme=scheme,
                blocked_address=str(address),
            )
        blocked_address = restricted_address(parsed_address)
        if blocked_address:
            return EgressDecision(
                allowed=False,
                reason="blocked_restricted_ip",
                url=str(url),
                normalized_url=normalized_url,
                host=host,
                port=port,
                scheme=scheme,
                blocked_address=blocked_address,
            )

    return EgressDecision(
        allowed=True,
        reason="allowed_public_http",
        url=str(url),
        normalized_url=normalized_url,
        host=host,
        port=port,
        scheme=scheme,
    )


def evaluate_browser_redirect_chain(
    hops: tuple[EgressHop, ...] | list[EgressHop],
    *,
    policy: BrowserEgressPolicy = DEFAULT_BROWSER_EGRESS_POLICY,
    allow_admin_dev_targets: bool = False,
) -> EgressDecision:
    """Evaluate an initial URL and every redirect target under the same policy."""

    last_decision: EgressDecision | None = None
    for index, hop in enumerate(hops):
        decision = evaluate_browser_egress_url(
            hop.url,
            policy=policy,
            resolved_addresses=hop.resolved_addresses,
            allow_admin_dev_targets=allow_admin_dev_targets,
        )
        last_decision = decision
        if not decision.allowed:
            return EgressDecision(
                allowed=decision.allowed,
                reason=decision.reason,
                url=decision.url,
                normalized_url=decision.normalized_url,
                host=decision.host,
                port=decision.port,
                scheme=decision.scheme,
                blocked_address=decision.blocked_address,
                redirect_index=index,
            )
    if not hops:
        return EgressDecision(allowed=False, reason="blocked_missing_host", url="", redirect_index=0)
    final = last_decision
    if final is None:
        return EgressDecision(allowed=False, reason="blocked_missing_host", url="", redirect_index=0)
    return EgressDecision(
        allowed=final.allowed,
        reason=final.reason,
        url=final.url,
        normalized_url=final.normalized_url,
        host=final.host,
        port=final.port,
        scheme=final.scheme,
        blocked_address=final.blocked_address,
        redirect_index=len(hops) - 1,
    )


def resolve_browser_egress_url_addresses(
    url: str,
    *,
    policy: BrowserEgressPolicy = DEFAULT_BROWSER_EGRESS_POLICY,
) -> tuple[str, ...] | None:
    """Resolve one browser URL hostname through the trusted server resolver.

    IP literals and already-blocked hostname forms do not need DNS resolution.
    Callers still must pass the returned addresses back through policy
    evaluation before navigating.
    """

    try:
        parsed = urlsplit(str(url).strip())
        parsed.port
    except ValueError:
        return None
    scheme = parsed.scheme.lower()
    if scheme not in {item.lower() for item in policy.allowed_schemes}:
        return None
    host = _normalize_host(parsed.hostname)
    if not host:
        return None
    port = parsed.port or _default_port(scheme)
    if _is_admin_dev_target(scheme=scheme, host=host, port=port, policy=policy):
        return None
    if host in METADATA_HOSTS or restricted_host(host):
        return None
    host_address = _parse_ip_address(host)
    if host_address is not None:
        return None
    try:
        addrinfo = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except OSError:
        return ()
    addresses = {str(item[4][0]) for item in addrinfo if item and len(item) >= 5 and item[4]}
    return tuple(sorted(addresses))


def _normalize_host(host: str | None) -> str | None:
    if host is None:
        return None
    normalized = host.strip().lower().rstrip(".")
    if not normalized:
        return None
    try:
        return normalized.encode("idna").decode("ascii")
    except UnicodeError:
        return normalized


def _default_port(scheme: str) -> int:
    return 443 if scheme == "https" else 80


def _normalize_url(parsed: SplitResult, *, scheme: str, host: str, port: int) -> str:
    default_port = _default_port(scheme)
    host_for_netloc = f"[{host}]" if ":" in host and not host.startswith("[") else host
    netloc = host_for_netloc if port == default_port else f"{host_for_netloc}:{port}"
    return urlunsplit((scheme, netloc, parsed.path or "/", parsed.query, ""))


def _is_admin_dev_target(*, scheme: str, host: str, port: int, policy: BrowserEgressPolicy) -> bool:
    candidate = EgressTarget(scheme=scheme, host=host, port=port).normalized()
    return candidate in {target.normalized() for target in policy.admin_dev_targets}


def _parse_ip_address(value: str) -> ipaddress.IPv4Address | ipaddress.IPv6Address | None | ValueError:
    try:
        if "%" in value:
            return ValueError("IPv6 zone identifiers are not allowed")
        return ipaddress.ip_address(value)
    except ValueError as exc:
        if ":" in value or _looks_like_ipv4_literal(value):
            return exc
        return None


def _looks_like_ipv4_literal(value: str) -> bool:
    return bool(value) and all(part.isdigit() for part in value.split("."))
