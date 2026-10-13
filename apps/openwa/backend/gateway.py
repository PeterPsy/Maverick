"""Bounded OpenWA REST transport. Credentials never enter URLs or responses."""
import base64
import http.client
import ipaddress
import json
import socket
from urllib.parse import urlsplit, urlencode

SECRET = "openwa-api-key"
MAX_BODY = 6 * 1024 * 1024
MAX_IMAGE_BYTES = 4 * 1024 * 1024
IMAGE_MIMETYPES = {"image/jpeg", "image/png", "image/webp", "image/gif"}

class GatewayError(Exception):
    def __init__(self, message: str, status: int = 502, code: str = "gateway_error"):
        super().__init__(message)
        self.status, self.code = status, code

    @property
    def uncertain_send(self):
        return self.status >= 500 or (self.status == 409 and self.code in {"gateway_error", "IDEMPOTENCY_OUTCOME_UNKNOWN"})

def normalize_origin(raw: object) -> str:
    if not isinstance(raw, str) or len(raw) > 300:
        raise GatewayError("Enter a valid gateway URL.", 400)
    raw = raw.strip()
    if any(ord(c) <= 32 or ord(c) == 127 for c in raw):
        raise GatewayError("Enter a valid gateway URL.", 400)
    try:
        parts = urlsplit(raw)
    except ValueError:
        raise GatewayError("Enter a valid gateway URL.", 400) from None
    if parts.username or parts.password or parts.query or parts.fragment or parts.path not in ("", "/", "/api", "/api/"):
        raise GatewayError("Use the gateway origin, without credentials or a path.", 400)
    try:
        port = parts.port
    except ValueError:
        raise GatewayError("Invalid gateway port.", 400) from None
    if parts.scheme == "http" and parts.hostname == "127.0.0.1" and port == 2785:
        return "http://127.0.0.1:2785"
    if parts.scheme != "https" or not parts.hostname or port not in (None, 443):
        raise GatewayError("Use HTTPS, or the local gateway at http://127.0.0.1:2785.", 400)
    if parts.hostname in ("localhost", "metadata.google.internal"):
        raise GatewayError("Private gateway hosts are not supported.", 400)
    return "https://" + parts.hostname.lower()

def _connection(origin: str):
    parts = urlsplit(normalize_origin(origin))
    if parts.scheme == "http":
        return http.client.HTTPConnection("127.0.0.1", 2785, timeout=12)
    try:
        addresses = socket.getaddrinfo(parts.hostname, 443, type=socket.SOCK_STREAM)
    except OSError:
        raise GatewayError("The gateway hostname could not be resolved.", 503, "gateway_unavailable") from None
    if not addresses or any(not ipaddress.ip_address(item[4][0]).is_global for item in addresses):
        raise GatewayError("The gateway must resolve to a public address.", 400)
    address = addresses[0][4][0]
    conn = http.client.HTTPSConnection(parts.hostname, 443, timeout=12)
    conn._create_connection = lambda endpoint, timeout, source_address=None, **kwargs: socket.create_connection((address, 443), timeout, source_address)
    return conn

class Gateway:
    def __init__(self, origin: str, key: object):
        self.origin = normalize_origin(origin)
        if not isinstance(key, str) or not key.strip() or len(key) > 512 or any(not 33 <= ord(c) <= 126 for c in key):
            raise GatewayError("Connect your OpenWA gateway first.", 409, "connection_required")
        self.key = key

    def request(self, method: str, route: str, body: dict | None = None, query: dict | None = None, idempotency_key: str | None = None):
        if not route.startswith("/") or ".." in route or "?" in route:
            raise GatewayError("Invalid gateway operation.", 400)
        path = "/api" + route
        if query:
            path += "?" + urlencode({k: v for k, v in query.items() if v is not None})
        headers = {"X-API-Key": self.key, "Accept": "application/json", "Content-Type": "application/json"}
        if idempotency_key:
            headers["Idempotency-Key"] = idempotency_key
        return _request(self.origin, method, path, headers, body)

    def read_image(self, route: str, max_bytes: int):
        if not route.startswith("/sessions/") or ".." in route or "?" in route:
            raise GatewayError("Invalid image operation.", 400)
        conn = _connection(self.origin)
        try:
            conn.request("GET", "/api" + route, headers={"X-API-Key": self.key, "Accept": "image/*"})
            response = conn.getresponse()
            if response.status != 200:
                messages = {401: "OpenWA rejected the API key.", 403: "This API key cannot read this image.",
                            404: "This image is no longer available from the gateway.",
                            429: "OpenWA is rate limiting requests. Try again later."}
                raise GatewayError(messages.get(response.status, "OpenWA could not read this image."), response.status)
            mimetype = (response.getheader("Content-Type") or "").split(";", 1)[0].strip().lower()
            if mimetype not in IMAGE_MIMETYPES:
                raise GatewayError("This message does not contain a supported image.", 415)
            content = response.read(max_bytes + 1)
            if len(content) > max_bytes:
                raise GatewayError("This image exceeds the requested size limit.", 413)
            if not content:
                raise GatewayError("The gateway returned an empty image.", 502)
            return {"mimetype": mimetype, "size_bytes": len(content), "content_base64": base64.b64encode(content).decode("ascii")}
        except (OSError, http.client.HTTPException):
            raise GatewayError("The image could not be loaded. Try again.", 503, "gateway_unavailable") from None
        finally:
            conn.close()

def _request(origin, method, path, headers, body=None):
    conn = _connection(origin)
    try:
        conn.request(method, path, body=None if body is None else json.dumps(body).encode(), headers=headers)
        response = conn.getresponse()
        content = response.read(MAX_BODY + 1)
        if len(content) > MAX_BODY:
            raise GatewayError("The gateway response is too large. Narrow your search.", 413)
        if response.status >= 300:
            messages = {401: "OpenWA rejected the API key.", 403: "This API key cannot perform that operation.",
                404: "The requested OpenWA resource was not found.", 409: "The send outcome is uncertain. Check the conversation before preparing a new send.",
                429: "OpenWA is rate limiting requests. Try again later.", 501: "Your WhatsApp engine does not support this operation."}
            code = "gateway_error"
            # Upstream messages and arbitrary codes may contain sensitive payloads.
            try:
                data = json.loads(content) if response.status in (409, 429) else None
            except (ValueError, UnicodeError):
                data = None
            if response.status == 409 and isinstance(data, dict) and data.get("code") in (
                "IDEMPOTENCY_KEY_IN_PROGRESS", "IDEMPOTENCY_OUTCOME_UNKNOWN"
            ):
                code = data["code"]
                if code == "IDEMPOTENCY_KEY_IN_PROGRESS":
                    messages[409] = "This send is still running. Wait, then retry with the same message."
            if response.status == 429 and isinstance(data, dict) and data.get("code") == "SEND_PACING_LIMITED":
                code = "SEND_PACING_LIMITED"
                messages[429] = "OpenWA's configured send allowance blocked this request before sending."
            raise GatewayError(messages.get(response.status, "OpenWA could not complete this request."), response.status, code)
        if response.status in (204, 205) and not content:
            return None
        try:
            return json.loads(content)
        except (ValueError, UnicodeError):
            raise GatewayError("The gateway returned an invalid response.") from None
    except (OSError, http.client.HTTPException):
        message = "The gateway is unreachable or the request timed out."
        if path.endswith(("/messages/send-text", "/messages/reply")):
            message += " The message may already have been sent. Check the conversation before retrying."
        raise GatewayError(message, 503, "gateway_unavailable") from None
    finally:
        conn.close()

def check_readiness(origin):
    data = _request(origin, "GET", "/api/health/ready", {"Accept": "application/json"})
    if not isinstance(data, dict) or data.get("status") != "ok":
        raise GatewayError("The OpenWA provider is not ready.", 503, "gateway_unavailable")
