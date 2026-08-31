"""Production plumbing for one atomic runtime-input classification manifest."""

from __future__ import annotations

from typing import Any

from core.runtime.provider_input_capture import (
    RuntimeProviderInputCaptureSource,
    capture_runtime_provider_input_classifications,
)
from core.runtime.public_content_authority_store import (
    runtime_public_content_authority_for_workspace,
)


def persist_runtime_provider_input_capture(
    state: Any,
    *,
    session: Any,
    turn_id: str,
    input_text: str,
    agent_instruction: str,
    orchestration: dict[str, object] | None,
    app_reference_entries: tuple[tuple[int, dict[str, object], str], ...],
    attachment_entries: tuple[
        tuple[int, dict[str, object], dict[str, object], str], ...
    ],
) -> None:
    """Persist exact materialized sources before their admission lookup."""
    sources: list[RuntimeProviderInputCaptureSource] = []
    if agent_instruction:
        sources.append(
            RuntimeProviderInputCaptureSource(
                "agent-instruction",
                "agent_instruction",
                "text/plain",
                agent_instruction,
            )
        )
    if input_text:
        sources.append(
            RuntimeProviderInputCaptureSource(
                "turn-prompt",
                "user_input",
                "text/plain",
                input_text,
            )
        )
    if orchestration is not None:
        sources.append(
            RuntimeProviderInputCaptureSource(
                "generalist-orchestration",
                "governed_context",
                "application/json",
                orchestration,
            )
        )
    sources.extend(
        RuntimeProviderInputCaptureSource(
            f"app-reference:{index}:metadata",
            "app_reference",
            "text/plain",
            content,
        )
        for index, _reference, content in app_reference_entries
    )
    sources.extend(
        RuntimeProviderInputCaptureSource(
            f"attachment:{index}:metadata",
            "attachment",
            "application/json",
            content,
        )
        for index, _attachment, content, _media_type in attachment_entries
    )
    runtime_store = getattr(state, "runtime_store", None)
    writer = getattr(
        runtime_store,
        "capture_turn_provider_input_classification_manifest",
        None,
    )
    if not sources or not callable(writer):
        return
    capture_runtime_provider_input_classifications(
        runtime_store,
        workspace_id=str(getattr(session, "workspace_id", "") or ""),
        session_id=str(getattr(session, "session_id", "") or ""),
        turn_id=str(turn_id or ""),
        sources=tuple(sources),
        public_content_authority=(
            runtime_public_content_authority_for_workspace(
                getattr(state, "workspace_store", None),
                str(getattr(session, "workspace_id", "") or ""),
            )
        ),
    )


__all__ = ["persist_runtime_provider_input_capture"]
