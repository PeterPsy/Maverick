"""Restricted network definitions for core egress checks."""

from __future__ import annotations

import ipaddress


RESTRICTED_HOSTS = frozenset(
    {
        "docker.for.mac.localhost",
        "docker.for.win.localhost",
        "gateway.docker.internal",
        "host.docker.internal",
        "hostmachine",
        "ip6-localhost",
        "ip6-loopback",
        "localhost",
        "kubernetes.docker.internal",
    }
)

METADATA_HOSTS = frozenset(
    {
        "metadata",
        "metadata.google.internal",
    }
)

RESTRICTED_NETWORKS = tuple(
    ipaddress.ip_network(cidr)
    for cidr in (
        "0.0.0.0/8",
        "10.0.0.0/8",
        "100.64.0.0/10",
        "100.100.100.200/32",
        "127.0.0.0/8",
        "169.254.0.0/16",
        "172.16.0.0/12",
        "192.0.0.0/24",
        "192.0.2.0/24",
        "192.168.0.0/16",
        "198.18.0.0/15",
        "198.51.100.0/24",
        "203.0.113.0/24",
        "224.0.0.0/4",
        "240.0.0.0/4",
        "::/128",
        "::1/128",
        "64:ff9b:1::/48",
        "100::/64",
        "2001:db8::/32",
        "fc00::/7",
        "fd00:ec2::254/128",
        "fe80::/10",
        "ff00::/8",
    )
)

NAT64_WELL_KNOWN_PREFIX = ipaddress.ip_network("64:ff9b::/96")


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
    if address.ipv4_mapped is not None:
        return address.ipv4_mapped
    if address.sixtofour is not None:
        return address.sixtofour
    if address in NAT64_WELL_KNOWN_PREFIX:
        return ipaddress.IPv4Address(int(address) & 0xFFFFFFFF)
    return None
