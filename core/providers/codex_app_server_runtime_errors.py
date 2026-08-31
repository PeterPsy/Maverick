"""Typed Codex app-server transport failures."""

from __future__ import annotations


TERMINAL_COMPLETION_GRACE_SECONDS = 1.0


def codex_error_info(params: dict[str, object]) -> str | None:
    """Return one bounded provider error category."""
    error = params.get("error") if isinstance(params.get("error"), dict) else {}
    value = str(error.get("codexErrorInfo") or "").strip()
    if not value or len(value) > 64 or not value.replace("_", "").isalnum():
        return None
    return value


def codex_terminal_failure_reason_code(error_info: str | None) -> str:
    """Map a terminal Codex category to one provider-neutral reason code."""
    return "provider_overloaded" if error_info == "serverOverloaded" else "provider_execution_failed"


def terminal_completion_wait(runtime, *, now: float) -> tuple[bool, float]:
    """Bound the wait for Codex's authoritative completion after a terminal error."""
    with runtime.event_lock:
        terminal_error_at = runtime.current_terminal_error_at
    if terminal_error_at is None:
        return False, 1.0
    remaining = terminal_error_at + TERMINAL_COMPLETION_GRACE_SECONDS - now
    return remaining <= 0, min(1.0, max(0.01, remaining))


class CodexAppServerRequestError(RuntimeError):
    """Structured JSON-RPC rejection returned by Codex app-server."""

    def __init__(self, method: str, *, code: int | None, message: str, data: object = None) -> None:
        super().__init__(f"`{method}` failed against Codex app-server: {message}")
        self.method = method
        self.code = code
        self.message = message
        self.data = data


class CodexAppServerDeliveryUncertainError(RuntimeError):
    """A request may have reached Codex but its acknowledgement was not observed."""
