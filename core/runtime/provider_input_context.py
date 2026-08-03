"""Transient governed context composition for runtime provider input."""

from __future__ import annotations

from typing import Any

from core.runtime.app_references import input_text_with_app_references
from core.runtime.attachments import input_text_with_attachment_links


def generalist_orchestration_input_text(state: Any, *, session: Any, input_text: str) -> str:
    """Attach root orchestration context without persisting it in the turn."""
    # Lazy import avoids the inter-agent service -> runtime submission cycle.
    from core.inter_agent.generalist_context import input_text_with_generalist_orchestration_context

    return input_text_with_generalist_orchestration_context(state, session=session, input_text=input_text)


def runtime_provider_input_text(
    state: Any,
    *,
    session: Any,
    input_text: str,
    app_references: list[dict[str, object]] | None,
    attachments: list[dict[str, object]] | None,
) -> str:
    """Build agentic provider input from governed context and materialized references."""
    governed_input = generalist_orchestration_input_text(state, session=session, input_text=input_text)
    return input_text_with_attachment_links(
        input_text=input_text_with_app_references(input_text=governed_input, app_references=app_references),
        attachments=attachments,
        workspace_root=session.workspace_root,
    )
