"""Canonical product taxonomy for model execution families."""

from __future__ import annotations

from dataclasses import dataclass

from core.providers.certified_execution_tcb import is_exact_codex_identity


NATIVE_AGENT_EXECUTION_FAMILY = "native_agent"
MAVERICK_AGENT_EXECUTION_FAMILY = "maverick_agent"
HOSTED_TEXT_EXECUTION_FAMILY = "hosted_text"


@dataclass(frozen=True)
class ExecutionFamilyDefinition:
    """One ordered product family shared by Core, Settings, and Chat."""

    family_id: str
    label: str
    description: str
    workspace_actions: bool


EXECUTION_FAMILIES = (
    ExecutionFamilyDefinition(
        family_id=NATIVE_AGENT_EXECUTION_FAMILY,
        label="Native Agents (CLI)",
        description=(
            "External coding-agent runtimes such as Codex, Claude Code, and "
            "Gemini CLI. They use their own agent loop and tools, while Maverick "
            "launches, connects to, and supervises them."
        ),
        workspace_actions=True,
    ),
    ExecutionFamilyDefinition(
        family_id=MAVERICK_AGENT_EXECUTION_FAMILY,
        label="Maverick Agents (API)",
        description=(
            "API models made agentic by Maverick. Maverick provides workspace "
            "context, tools, the execution loop, approvals, finalization, and "
            "recovery."
        ),
        workspace_actions=True,
    ),
    ExecutionFamilyDefinition(
        family_id=HOSTED_TEXT_EXECUTION_FAMILY,
        label="Text-only Models (API)",
        description=(
            "API models without workspace tools or an action loop. They generate "
            "text from the context provided by Maverick but cannot perform "
            "workspace actions."
        ),
        workspace_actions=False,
    ),
)

NO_WORKSPACE_ACTIONS_MESSAGE = "No workspace tools or actions."


def execution_family_catalog() -> tuple[ExecutionFamilyDefinition, ...]:
    """Return the immutable normative family catalog in display order."""
    return EXECUTION_FAMILIES


def effective_agentic_execution_family(
    explicit_family: str | None,
    *,
    runtime_engine_id: str,
    adapter_id: str,
    model_provider_id: str,
    provider_protocol: str,
) -> str:
    """Resolve an agentic family without trusting provider capability flags.

    Old Codex profiles predate the family field. Their exact, closed identity is
    the only legacy inference allowed; arbitrary vendor labels never grant an
    agentic classification.
    """
    normalized = str(explicit_family or "").strip()
    if normalized in {
        NATIVE_AGENT_EXECUTION_FAMILY,
        MAVERICK_AGENT_EXECUTION_FAMILY,
    }:
        return normalized
    if normalized:
        return normalized
    if is_exact_codex_identity(
        runtime_engine_id=runtime_engine_id,
        adapter_id=adapter_id,
        model_provider_id=model_provider_id,
        provider_protocol=provider_protocol,
    ):
        return NATIVE_AGENT_EXECUTION_FAMILY
    return ""
