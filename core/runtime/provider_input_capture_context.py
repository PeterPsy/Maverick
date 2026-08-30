"""Atomic provider-input capture and exact snapshot composition."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from core.runtime.provider_input_context import (
    RuntimeProviderInputSource,
    generalist_orchestration_input_text,
    generalist_orchestration_source,
    runtime_provider_input_sources,
    runtime_provider_input_text,
)


@dataclass(frozen=True)
class CapturedRuntimeProviderInput:
    """One immutable provider-input snapshot and its classified source blocks."""

    input_text: str
    sources: tuple[RuntimeProviderInputSource, ...]


def capture_runtime_provider_input(
    state: Any,
    *,
    session: Any,
    turn_id: str,
    input_text: str,
    app_references: list[dict[str, object]] | None,
    attachments: list[dict[str, object]] | None,
) -> CapturedRuntimeProviderInput:
    """Capture, classify, and compose one exact pre-dispatch input snapshot."""
    orchestration = generalist_orchestration_source(state, session=session)
    sources = runtime_provider_input_sources(
        state,
        session=session,
        turn_id=turn_id,
        input_text=input_text,
        app_references=app_references,
        attachments=attachments,
        orchestration=orchestration,
    )
    return CapturedRuntimeProviderInput(
        input_text=runtime_provider_input_text(
            state,
            session=session,
            input_text=input_text,
            app_references=app_references,
            attachments=attachments,
            orchestration=orchestration,
        ),
        sources=sources,
    )


__all__ = [
    "CapturedRuntimeProviderInput",
    "capture_runtime_provider_input",
    "generalist_orchestration_input_text",
]
