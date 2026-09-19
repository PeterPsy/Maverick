"""Bounded, credential-free HTTPS verification against the approved public host."""
import hashlib
import http.client
import ipaddress
import socket
import ssl
import time

from .errors import AppError
from .policy import MAX_FILE


def public_connection(hostname):
    addresses = socket.getaddrinfo(hostname, 443, type=socket.SOCK_STREAM)
    ips = list(dict.fromkeys(item[4][0] for item in addresses))
    if not ips or any(not ipaddress.ip_address(ip).is_global for ip in ips):
        raise AppError("public_probe_address_denied", 503)
    connection = http.client.HTTPSConnection(hostname, 443, timeout=5, context=ssl.create_default_context())
    connection._create_connection = lambda address, timeout, source_address: socket.create_connection((ips[0], 443), timeout, source_address)
    return connection


def verify_tls(hostname):
    try:
        connection = public_connection(hostname)
        try:
            connection.connect()
        finally:
            connection.close()
    except (OSError, http.client.HTTPException) as error:
        raise AppError("public_tls_not_ready", 503) from error


def verify_https(hostname, release, entrypoint_hash):
    started = time.monotonic()
    try:
        # Pin the selected address; TLS SNI and certificate validation use hostname.
        connection = public_connection(hostname)
        try:
            connection.request("GET", "/", headers={"Host": hostname, "Accept": "text/html", "Cache-Control": "no-cache"})
            response = connection.getresponse()
            content = response.read(MAX_FILE + 1)
            if (response.status != 200 or response.getheader("X-External-Release") != release["release_id"]
                    or len(content) > MAX_FILE or hashlib.sha256(content).hexdigest() != entrypoint_hash):
                raise AppError("public_verification_failed", 503)
            return {"status": "healthy", "checked_at": time.time(), "elapsed_ms": round((time.monotonic() - started) * 1000)}
        finally:
            connection.close()
    except (OSError, http.client.HTTPException) as error:
        raise AppError("public_verification_failed", 503) from error
