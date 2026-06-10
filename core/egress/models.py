"""Network egress policy models."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from core.egress.manifest import browser_egress_policy_manifest


DecisionReason = Literal[
    "allowed_public_http",
    "allowed_admin_dev_target",
    "blocked_admin_dev_target_not_enabled",
    "blocked_disallowed_scheme",
    "blocked_missing_host",
    "blocked_invalid_port",
    "blocked_invalid_ip_literal",
    "blocked_metadata_host",
    "blocked_restricted_host",
    "blocked_dns_resolution_required",
    "blocked_no_resolved_addresses",
    "blocked_restricted_ip",
]


@dataclass(frozen=True)
class EgressTarget:
    """Exact dev egress target that may bypass private-network denial."""

    scheme: str
    host: str
    port: int

    def normalized(self) -> "EgressTarget":
        return EgressTarget(scheme=self.scheme.lower(), host=self.host.lower().rstrip("."), port=self.port)


@dataclass(frozen=True)
class BrowserEgressPolicy:
    """Fail-closed browser egress policy for sidecar-controlled browser work."""

    allowed_schemes: tuple[str, ...] = field(
        default_factory=lambda: tuple(_manifest_sequence("allowed_schemes"))
    )
    admin_dev_targets: tuple[EgressTarget, ...] = field(
        default_factory=lambda: tuple(_manifest_admin_dev_targets())
    )
    require_dns_resolution_for_hostnames: bool = True


def _manifest_sequence(key: str) -> list[str]:
    values = browser_egress_policy_manifest().get(key)
    if not isinstance(values, list) or not all(isinstance(item, str) and item for item in values):
        raise ValueError(f"Browser egress policy manifest {key} must be a non-empty string list.")
    return values


def _manifest_admin_dev_targets() -> list[EgressTarget]:
    values = browser_egress_policy_manifest().get("admin_dev_targets")
    if not isinstance(values, list) or not values:
        raise ValueError("Browser egress policy manifest admin_dev_targets must be a non-empty list.")
    targets: list[EgressTarget] = []
    for value in values:
        if not isinstance(value, dict):
            raise ValueError("Browser egress policy manifest admin_dev_targets entries must be objects.")
        scheme = value.get("scheme")
        host = value.get("host")
        port = value.get("port")
        if not isinstance(scheme, str) or not isinstance(host, str) or type(port) is not int:
            raise ValueError("Browser egress policy manifest admin_dev_targets entries require scheme, host, and port.")
        targets.append(EgressTarget(scheme=scheme, host=host, port=port).normalized())
    return targets


DEFAULT_BROWSER_EGRESS_POLICY = BrowserEgressPolicy()


@dataclass(frozen=True)
class EgressDecision:
    """Auditable decision for one requested URL."""

    allowed: bool
    reason: DecisionReason
    url: str
    normalized_url: str | None = None
    host: str | None = None
    port: int | None = None
    scheme: str | None = None
    blocked_address: str | None = None
    redirect_index: int | None = None


@dataclass(frozen=True)
class EgressHop:
    """One URL hop in an initial navigation or redirect chain."""

    url: str
    resolved_addresses: tuple[str, ...] = ()
