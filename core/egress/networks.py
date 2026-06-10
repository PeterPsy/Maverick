"""Restricted network definitions for core egress checks."""

from __future__ import annotations

import ipaddress

from core.egress.manifest import browser_egress_policy_manifest

_POLICY_MANIFEST = browser_egress_policy_manifest()

RESTRICTED_HOSTS = frozenset(str(host).lower().rstrip(".") for host in _POLICY_MANIFEST["restricted_hosts"])

METADATA_HOSTS = frozenset(str(host).lower().rstrip(".") for host in _POLICY_MANIFEST["metadata_hosts"])

RESTRICTED_NETWORKS = tuple(ipaddress.ip_network(cidr) for cidr in _POLICY_MANIFEST["restricted_networks"])

EMBEDDED_IPV4_EXTRACTORS = tuple(
    (ipaddress.ip_network(item["prefix"]), int(item["shift"])) for item in _POLICY_MANIFEST["embedded_ipv4_extractors"]
)


def restricted_host(host: str) -> str | None:
    """Return the blocked host string when a hostname is known local-only."""

    if host in RESTRICTED_HOSTS or host.endswith(".localhost"):
        return host
    return None


def restricted_address(address: ipaddress.IPv4Address | ipaddress.IPv6Address) -> str | None:
    """Return the blocked address string when an address is not public egress safe."""

    if not address.is_global:
        return str(address)
    embedded_v4 = _embedded_ipv4(address)
    if embedded_v4 is not None and restricted_address(embedded_v4):
        return str(address)
    for network in RESTRICTED_NETWORKS:
        if address in network:
            return str(address)
    return None


def _embedded_ipv4(address: ipaddress.IPv4Address | ipaddress.IPv6Address) -> ipaddress.IPv4Address | None:
    if not isinstance(address, ipaddress.IPv6Address):
        return None
    value = int(address)
    for network, shift in EMBEDDED_IPV4_EXTRACTORS:
        if address in network:
            return ipaddress.IPv4Address((value >> shift) & 0xFFFFFFFF)
    return None
