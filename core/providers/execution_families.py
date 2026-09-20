"""Canonical product taxonomy for model execution families."""

from __future__ import annotations

from dataclasses import dataclass

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
        label="CLI models",
        description="Models running through native command-line agents.",
        workspace_actions=True,
    ),
    ExecutionFamilyDefinition(
        family_id=MAVERICK_AGENT_EXECUTION_FAMILY,
        label="API models",
        description="Models running through Maverick's agentic API loop.",
        workspace_actions=True,
    ),
)

NO_WORKSPACE_ACTIONS_MESSAGE = "No workspace tools or actions."


def is_exact_codex_identity(
    *,
    runtime_engine_id: str,
    adapter_id: str,
    model_provider_id: str,
    provider_protocol: str,
) -> bool:
    """Recognize the built-in Codex integration from its closed identity tuple."""
    return (
        runtime_engine_id == "codex"
        and adapter_id == "codex-app-server"
        and model_provider_id == "codex"
        and provider_protocol == "codex-app-server-stdio"
    )


def execution_family_catalog() -> tuple[ExecutionFamilyDefinition, ...]:
    """Return the immutable normative family catalog in display order."""
    return EXECUTION_FAMILIES


def effective_agentic_execution_family(
    *,
    runtime_engine_id: str,
    adapter_id: str,
    model_provider_id: str,
    provider_protocol: str,
) -> str:
    """Derive the product family directly from the configured runtime identity."""
    if is_exact_codex_identity(
        runtime_engine_id=runtime_engine_id,
        adapter_id=adapter_id,
        model_provider_id=model_provider_id,
        provider_protocol=provider_protocol,
    ):
        return NATIVE_AGENT_EXECUTION_FAMILY
    if runtime_engine_id == "maverick-tool-loop":
        return MAVERICK_AGENT_EXECUTION_FAMILY
    if runtime_engine_id in {"codex", "claude-code", "antigravity-cli"}:
        return NATIVE_AGENT_EXECUTION_FAMILY
    return ""
