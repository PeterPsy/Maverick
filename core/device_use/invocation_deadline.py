"""Frozen native operation budgets; the relay adds only delivery grace."""

DEFAULT_INVOCATION_TIMEOUT_SECONDS = 180.0
RESULT_DELIVERY_GRACE_SECONDS = 5.0


def invocation_timeout_seconds(tool: str, action: str) -> float:
    if tool == "mac_code" and action == "select_project":
        return 300.0
    if tool != "mac_project":
        return DEFAULT_INVOCATION_TIMEOUT_SECONDS
    if action in {"transcribe_media", "prepare_subclip"}:
        return 900.0
    if action == "run_project_script":
        return 1200.0
    return 300.0
