"""Isolated-origin background access with the issuing app's exact authority."""

import json
from types import SimpleNamespace


GRANT_PATH = "/.well-known/loopino-app-background/grant"
REQUEST_PATH = "/.well-known/loopino-app-background/request"
MAX_BODY_BYTES = 8 * 1024 * 1024


async def handle_background_request(state, *, scope, receive, send, host, start_path, forward,
                                    validate_session, current_frame, platform_scope, send_json):
    path = scope["path"]
    method = str(scope.get("method") or "GET").upper()
    headers = {}
    for name, value in scope.get("headers", []):
        headers.setdefault(name.lower(), []).append(value.decode("latin1"))

    async def deny(error, status=403):
        await send_json(send, {"error": error}, status=status, headers=[("Cache-Control", "no-store")])

    if scope.get("query_string"):
        await deny("background_url_must_be_clean", 400)
        return
    if path == GRANT_PATH:
        if method != "POST":
            await deny("method_not_allowed", 405)
            return
        resolved = await validate_session(state, scope=scope, send=send, host=host, start_path=start_path)
        if resolved is None:
            return
        _token, session = resolved
        if session.binding.widget_id or headers.get(b"origin") != [session.binding.origin] or headers.get(b"sec-fetch-site") != ["same-origin"]:
            await deny("csrf_proof_required")
            return
        try:
            raw = await read_body(receive, 4096)
            body = json.loads(raw)
            if not isinstance(body, dict) or set(body) != {"client_origin", "actions"}:
                raise ValueError("invalid_background_grant")
            value = state.app_background_grants.issue(session.binding, body["client_origin"], body["actions"])
        except (ValueError, KeyError) as error:
            await deny(str(error) if str(error).startswith(("invalid_background", "background_grant")) else "invalid_background_grant", 400)
            return
        await send_json(send, {"token": value}, status=201, headers=[("Cache-Control", "no-store")])
        return

    if method not in {"POST", "DELETE"}:
        await deny("method_not_allowed", 405)
        return
    authorization = headers.get(b"authorization", [])
    origins = headers.get(b"origin", [])
    if len(authorization) != 1 or not authorization[0].startswith("Bearer ") or len(origins) != 1:
        await deny("background_unauthorized")
        return
    value = authorization[0][7:]
    grant = state.app_background_grants.validate(value, host=host, client_origin=origins[0])
    if grant is None:
        await deny("background_unauthorized")
        return
    # Recheck current login, workspace, membership, visibility and app generation
    # for every request, even when its original Chrome setup document is gone.
    session = SimpleNamespace(binding=grant.binding)
    if current_frame(state, session, start_path=start_path) is None:
        state.app_background_grants.revoke(value)
        await deny("background_authorization_expired")
        return
    if method == "DELETE":
        state.app_background_grants.revoke(value)
        await send_json(send, {"revoked": True}, status=200, headers=[("Cache-Control", "no-store")])
        return
    try:
        raw = await read_body(receive, MAX_BODY_BYTES)
        body = json.loads(raw)
        if not isinstance(body, dict) or body.get("action") not in grant.actions:
            await deny("background_action_forbidden")
            return
    except (ValueError, TypeError):
        await deny("invalid_background_request", 400)
        return
    if current_frame(state, session, start_path=start_path) is None:
        state.app_background_grants.revoke(value)
        await deny("background_authorization_expired")
        return
    state.app_background_grants.touch(value)
    transformed = platform_scope(scope, session, websocket=False)
    transformed["path"] = f"/api/apps/{grant.binding.mount_app_id or grant.binding.app_id}/backend"
    # The transport bearer authorizes this route only; app entrypoints never see it.
    transformed["headers"] = [(name, content) for name, content in transformed["headers"] if name.lower() not in {b"authorization", b"content-length"}]
    transformed["headers"].append((b"content-length", str(len(raw)).encode()))

    delivered = False
    async def replay():
        nonlocal delivered
        if not delivered:
            delivered = True
            return {"type": "http.request", "body": raw, "more_body": False}
        return await receive()

    async def no_cookies(message):
        if message["type"] == "http.response.start":
            message = {**message, "headers": [(name, content) for name, content in message.get("headers", []) if name.lower() not in {b"set-cookie", b"cache-control"}] + [(b"cache-control", b"no-store")]}
        await send(message)

    await forward(transformed, replay, no_cookies)


async def read_body(receive, limit):
    chunks, size = [], 0
    while True:
        event = await receive()
        if event["type"] != "http.request":
            raise ValueError("request_disconnected")
        chunk = event.get("body", b"")
        size += len(chunk)
        if size > limit:
            raise ValueError("request_too_large")
        chunks.append(chunk)
        if not event.get("more_body", False):
            return b"".join(chunks)
