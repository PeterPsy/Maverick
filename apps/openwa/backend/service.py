"""Native authentication, secrets and events around OpenWA operations."""
import hashlib
import json
from actions import READ_ACTIONS, WRITE_ACTIONS, integer, perform, text
from gateway import Gateway, GatewayError, SECRET, normalize_origin
from state import configuration, save_configuration, notifications, dismiss, notify

def event(resource):
    return {"type": "loopino.app.data-changed", "resource": resource}

def handle(payload, body=None):
    body = payload.body if body is None else body
    action = body.get("action", "status")
    if action == "references.manifest":
        return {"app_id": "openwa", "entity_types": []}
    user = payload.user_id
    if not user:
        raise GatewayError("A trusted Loopino user is required.", 403)
    secrets = payload.raw.get("app_secrets", {})
    key = secrets.get(SECRET) if isinstance(secrets, dict) else None
    config = configuration(payload.data_root)
    if action in {"status", "connection.get"}:
        return {"connection": {**config, "credential_available": bool(key)}, "can_configure": payload.platform_role == "admin",
                "source": {"repository": "https://github.com/rmyndharis/OpenWA", "version": "0.24.0"},
                "send_scope": hashlib.sha256(json.dumps([payload.data_root, user, config["url"]]).encode()).hexdigest()}
    if action == "connection.save":
        if payload.platform_role != "admin":
            raise GatewayError("Only a platform administrator can configure the gateway.", 403)
        if "api_key" in body:
            raise GatewayError("Manage the OpenWA API key and its app grant in Loopino Vault.", 400)
        origin = normalize_origin(body.get("url"))
        info = Gateway(origin, key).request("POST", "/auth/validate", {})
        if not isinstance(info, dict) or info.get("valid") is not True:
            raise GatewayError("OpenWA could not validate this API key.", 401)
        value = {"url": origin, "configured": True, "role": info.get("role", "viewer"), "engine": info.get("engineType"), "scoped": bool(info.get("scoped"))}
        save_configuration(payload.data_root, value)
        notify(payload.data_root, user, "gateway-connected", "OpenWA connected", "Your WhatsApp gateway is ready. Link a session to begin.", "")
        return {"connection": value, "app_events": [event("connection"), event("notifications")]}
    if action == "connection.test":
        return {"gateway": Gateway(config["url"], key).request("POST", "/auth/validate", {})}
    if action == "notifications.list":
        return notifications(payload.data_root, user, integer(body, "offset", 0, 0, 100000), integer(body, "limit", 50, 1, 100))
    if action == "notifications.dismiss":
        dismiss(payload.data_root, user, text(body, "id", 200))
        return {"ok": True, "app_events": [event("notifications")]}
    if action not in READ_ACTIONS | WRITE_ACTIONS:
        raise GatewayError("Unknown operation.", 400)
    try:
        data = perform(Gateway(config["url"], key), action, body)
    except GatewayError as error:
        if action in {"messages.send", "messages.reply"} and error.uncertain_send:
            key_id = body.get("idempotency_key")
            if isinstance(key_id, str):
                notify(payload.data_root, user, "send-" + key_id[:100], "Check your WhatsApp send", str(error), str(body.get("session_id", "")))
        raise
    return {"data": data, **({"app_events": [event("sessions"), event("messages")]} if action in WRITE_ACTIONS else {})}
