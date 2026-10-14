"""Public response envelope for scheduled operations across app entrypoints."""


def envelope(result, *, flattened=False, data_root=None):
    result = dict(result or {})
    changed = result.pop("_scheduled_changed", False)
    notifications = result.pop("_notifications_changed", False)
    response = {"status_code": 200}
    for key in ("runtime_session_requests", "runtime_turn_interrupt_requests", "next_due_in_seconds"):
        if key in result:
            response[key] = result.pop(key)
    if flattened:
        # Agent surfaces only enqueue app-owned work. The hosted hook owns runtime
        # admission with the full platform context and the persisted initiating actor.
        queued = response.pop("runtime_session_requests", [])
        response.pop("runtime_turn_interrupt_requests", None)
        if queued:
            from scheduled_store import connection
            with connection(data_root, write=True) as db:
                db.executemany("UPDATE scheduled_requests SET status='queued' WHERE id=? AND status='launching'",
                               [(request["request_id"],) for request in queued])
            response["queued"] = True
            response["next_due_in_seconds"] = 1
    resources = []
    if changed:
        resources += ["scheduled-chats", "notifications"]
    elif notifications:
        resources += ["notifications"]
    response["app_events"] = [{"type": "loopino.app.data-changed", "resource": resource} for resource in resources]
    if flattened:
        response.update(result)
    else:
        response["json"] = result
    return response
