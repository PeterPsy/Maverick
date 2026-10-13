"""Explicit domain operations over OpenWA; no arbitrary route forwarding."""
import re
from urllib.parse import quote
from gateway import GatewayError, MAX_IMAGE_BYTES

READ_ACTIONS = {"sessions.list", "session.get", "session.qr", "chats.list", "contacts.list", "messages.list", "messages.image", "webhooks.list", "templates.list"}
WRITE_ACTIONS = {"session.create", "session.start", "session.stop", "session.logout", "session.pair", "messages.send", "messages.reply"}

def text(body, name, limit, optional=False, strip=True):
    value = body.get(name)
    if optional and value is None:
        return None
    if not isinstance(value, str) or not value.strip() or len(value) > limit or "\x00" in value:
        raise GatewayError(f"A valid {name.replace('_', ' ')} is required.", 400)
    return value.strip() if strip else value

def integer(body, name, default, low, high):
    value = body.get(name, default)
    if isinstance(value, bool) or not isinstance(value, int) or not low <= value <= high:
        raise GatewayError(f"Invalid {name}.", 400)
    return value

def session_id(body):
    value = text(body, "session_id", 128)
    if not re.fullmatch(r"[A-Za-z0-9_-]+", value):
        raise GatewayError("Invalid session id.", 400)
    return value

def chat_id(body):
    value = text(body, "chat_id", 150)
    if not re.fullmatch(r"[A-Za-z0-9_.:+-]+@(c\.us|s\.whatsapp\.net|g\.us|lid|newsletter)", value):
        raise GatewayError("Use a full WhatsApp chat id, or select a conversation.", 400)
    return value

def perform(gateway, action, body):
    if action == "sessions.list":
        return gateway.request("GET", "/sessions", query={"limit": integer(body, "limit", 100, 1, 100), "offset": integer(body, "offset", 0, 0, 100000)})
    if action == "session.create":
        return gateway.request("POST", "/sessions", {"name": text(body, "name", 100)})
    sid = session_id(body)
    root = "/sessions/" + quote(sid, safe="")
    if action == "session.get":
        return gateway.request("GET", root)
    if action == "session.qr":
        return gateway.request("GET", root + "/qr")
    if action == "session.start":
        try:
            return gateway.request("POST", root + "/start", {})
        except GatewayError as error:
            if error.status != 503:
                raise
            # Chromium cold starts outlive HTTP calls. The live session is the job status.
            current = gateway.request("GET", root)
            if isinstance(current, dict) and current.get("engineLoaded") and current.get("status") in {"initializing", "authenticating", "qr_ready", "ready"}:
                return current
            raise error
    if action in {"session.stop", "session.logout"}:
        return gateway.request("POST", root + "/" + action.split(".")[1], {})
    if action == "session.pair":
        phone = text(body, "phone", 20)
        if not re.fullmatch(r"[1-9][0-9]{7,14}", phone):
            raise GatewayError("Enter the phone number with country code, using digits only.", 400)
        return gateway.request("POST", root + "/pairing-code", {"phoneNumber": phone})
    if action in {"chats.list", "contacts.list", "webhooks.list", "templates.list"}:
        limit, offset = integer(body, "limit", 100, 1, 100), integer(body, "offset", 0, 0, 100000)
        if action in {"webhooks.list", "templates.list"}:
            rows = gateway.request("GET", root + "/" + action.split(".")[0])
            return rows[offset:offset + limit] if isinstance(rows, list) else rows
        return gateway.request("GET", root + "/" + action.split(".")[0], query={"limit": limit, "offset": offset})
    if action == "messages.list":
        return gateway.request("GET", root + "/messages", query={"chatId": chat_id(body), "limit": integer(body, "limit", 50, 1, 100),
            "offset": integer(body, "offset", 0, 0, 100000), "inlineMedia": "false"})
    if action == "messages.image":
        cid = chat_id(body)
        mid = text(body, "message_id", 200)
        route = root + "/messages/" + quote(cid, safe="") + "/" + quote(mid, safe="") + "/media"
        return gateway.read_image(route, integer(body, "max_bytes", MAX_IMAGE_BYTES, 1, MAX_IMAGE_BYTES))
    if action in {"messages.send", "messages.reply"}:
        key = text(body, "idempotency_key", 100)
        if not re.fullmatch(r"[A-Za-z0-9_-]{12,100}", key):
            raise GatewayError("An idempotency key is required for every send.", 400)
        data = {"chatId": chat_id(body), "text": text(body, "text", 4096, strip=False)}
        route = "/messages/send-text"
        if action == "messages.reply":
            data["quotedMessageId"] = text(body, "message_id", 200)
            route = "/messages/reply"
        return gateway.request("POST", root + route, data, idempotency_key=key)
    raise GatewayError("Unknown operation.", 400)
