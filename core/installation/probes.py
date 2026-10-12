"""Public HTTPS checks pinned to the planned server address."""

import http.client
import json
import secrets
import socket
import ssl

from core.installation.errors import InstallationError
from core.installation.validation import hostname, public_ip


def https_probe(host: str, address: str, path: str = "/health") -> dict:
    if not host.startswith(("af-", "sc-")):
        hostname(host)
    address = public_ip(address)
    context = ssl.create_default_context()
    with socket.create_connection((address, 443), timeout=8) as connection:
        with context.wrap_socket(connection, server_hostname=host) as secure:
            certificate = secure.getpeercert()
            secure.sendall((f"GET {path} HTTP/1.1\r\nHost: {host}\r\nConnection: close\r\n\r\n").encode())
            response = http.client.HTTPResponse(secure)
            response.begin()
            body = response.read(8193)
            if len(body) > 8192:
                raise InstallationError("verification_response_too_large")
            result = {"status": response.status, "tls_valid": True,
                      "expires_at": certificate.get("notAfter"), "host": host}
            if path.startswith("/api/installation/probe/"):
                result["proof"] = json.loads(body)
            return result


def verify_web(host: str, address: str, *, probe=https_probe) -> dict:
    results = []
    for target in (host, "af-" + secrets.token_hex(12) + ".sidecars." + host,
                   "sc-" + secrets.token_hex(12) + ".sidecars." + host):
        try:
            result = probe(target, address, "/health" if target == host else "/")
            result["healthy"] = result["status"] == (200 if target == host else 401)
        except (OSError, ValueError):
            result = {"host": target, "healthy": False, "tls_valid": False}
        results.append(result)
    return {"healthy": all(item["healthy"] for item in results), "checks": results}
