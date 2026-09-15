"""Positive initialization check for the isolated Codex Research process."""

from __future__ import annotations

from collections.abc import Callable

from core.providers.codex_app_server_runtime_thread_params import (
    codex_initialize_params,
)
from core.providers.provider_codex_research import (
    validate_codex_research_initialize,
)


def initialize_codex_runtime(
    runtime,
    *,
    session,
    send_request: Callable,
    timeout: float,
) -> None:
    result = send_request(
        runtime,
        "initialize",
        codex_initialize_params(session=session),
        timeout=timeout,
    )
    if runtime.research:
        validate_codex_research_initialize(
            result,
            expected_home=str(runtime.runtime_home or ""),
        )
