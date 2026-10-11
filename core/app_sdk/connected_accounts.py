"""SDK HTTP transport for opaque, invocation-scoped connected-account access."""

import base64
from email.message import Message
from io import BytesIO
import json
import socket
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen as direct_urlopen
from urllib.response import addinfourl


def account_for_capability(payload, capability):
    return next((item for item in payload.get("external_accounts", [])
                 if item.get("provider") == "google" and capability in item.get("services", [])), None)


def account_urlopen(request, *args, **kwargs):
    """Use the private Core broker for opaque tokens; normal HTTP is unchanged."""
    if not isinstance(request, Request):
        return direct_urlopen(request, *args, **kwargs)
    authorization = next((value for key, value in request.header_items() if key.lower() == "authorization"), "")
    marker = "Bearer maverick-account:"
    if not authorization.startswith(marker):
        return direct_urlopen(request, *args, **kwargs)
    try:
        descriptor = json.loads(base64.urlsafe_b64decode(authorization[len(marker):]))
        body = request.data or b""
        if not isinstance(body, bytes):
            raise ValueError("Connected-account request bodies must be bytes.")
        wire = json.dumps({"capability": descriptor["capability"], "method": request.get_method(),
            "url": request.full_url, "headers": {key: value for key, value in request.header_items() if key.lower() != "authorization"},
            "body_base64": base64.b64encode(body).decode()}, separators=(",", ":")).encode() + b"\n"
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as connection:
            connection.settimeout(kwargs.get("timeout", 30))
            connection.connect(descriptor["socket"])
            connection.sendall(wire)
            with connection.makefile("rb") as stream:
                raw = stream.readline(60 * 1024 * 1024 + 1)
        if len(raw) > 60 * 1024 * 1024 or not raw.endswith(b"\n"):
            raise ValueError("Invalid connected-account response.")
        result = json.loads(raw)
        headers = Message()
        for key, value in result.get("headers", {}).items():
            headers[key] = value
        status = int(result.get("status", 502))
        data = base64.b64decode(result.get("body_base64", ""), validate=True) if result.get("ok") else json.dumps({"error": result.get("error", "account_request_denied")}).encode()
        if status >= 400 or not result.get("ok"):
            raise HTTPError(request.full_url, status, "Connected account request failed", headers, BytesIO(data))
        return addinfourl(BytesIO(data), headers, request.full_url, status)
    except HTTPError:
        raise
    except (OSError, ValueError, KeyError, TypeError):
        raise URLError("Connected account broker is unavailable") from None
