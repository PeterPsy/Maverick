"""Network egress policy models."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal


DecisionReason = Literal[
    "allowed_public_http",
    "allowed_admin_dev_target",
    "blocked_admin_dev_target_not_enabled",
    "blocked_disallowed_scheme",
    "blocked_missing_host",
    "blocked_invalid_port",
    "blocked_invalid_ip_literal",
    "blocked_metadata_host",
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

    allowed_schemes: tuple[str, ...] = ("http", "https")
    admin_dev_targets: tuple[EgressTarget, ...] = field(
        default_factory=lambda: (EgressTarget(scheme="http", host="hostmachine", port=8000),)
    )
    require_dns_resolution_for_hostnames: bool = True


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
