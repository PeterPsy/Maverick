"""Restricted network definitions for core egress checks."""

from __future__ import annotations

import ipaddress


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


def restricted_address(address: ipaddress.IPv4Address | ipaddress.IPv6Address) -> str | None:
    """Return the blocked address string when an address is not public egress safe."""

    if not address.is_global:
        return str(address)
    for network in RESTRICTED_NETWORKS:
        if address in network:
            return str(address)
    return None
