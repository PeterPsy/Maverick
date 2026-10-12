"""HTTPS navigation for the user-connected interactive Agent tab."""

import ipaddress
import re
import socket
from urllib.parse import urlsplit, urlunsplit

from errors import BrowserValidationError


def website_url(value: object) -> str:
    if not isinstance(value, str) or not 1 <= len(value) <= 4096 or "\\" in value or any(c.isspace() or ord(c) < 32 for c in value):
        raise BrowserValidationError("A valid HTTPS website URL is required.", field="url")
    try:
        url = urlsplit(value)
        host = (url.hostname or "").encode("idna").decode("ascii").lower().rstrip(".")
        if url.scheme != "https" or url.port not in (None, 443) or url.username is not None or url.password is not None:
            raise ValueError()
        if not host or ":" in host or host == "localhost" or host.endswith((".localhost", ".local", ".internal")):
            raise ValueError()
        try:
            address = ipaddress.ip_address(socket.inet_aton(host))
        except OSError:
            if not re.fullmatch(r"(?=.{1,253}$)[a-z0-9](?:[a-z0-9.-]*[a-z0-9])?", host) or "." not in host or any(not label or len(label) > 63 or label.startswith("-") or label.endswith("-") for label in host.split(".")):
                raise ValueError()
        else:
            if not address.is_global:
                raise ValueError()
            host = str(address)
    except (ValueError, UnicodeError):
        raise BrowserValidationError("Use an HTTPS website without credentials or a local network address.", field="url") from None
    return urlunsplit(("https", host, url.path or "/", url.query, url.fragment))
