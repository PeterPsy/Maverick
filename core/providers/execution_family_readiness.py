"""Necessary runtime readiness checks for agentic model configurations."""

from __future__ import annotations

from dataclasses import dataclass

from core.providers.errors import ProviderNotFoundError
from core.providers.execution_families import (
    MAVERICK_AGENT_EXECUTION_FAMILY,
    NATIVE_AGENT_EXECUTION_FAMILY,
    effective_agentic_execution_family,
)
from core.providers.native_agent_catalog import native_agent_model_provider_connected


@dataclass(frozen=True)
class AgenticFamilyReadiness:
    """Whether the concrete runtime needed by a model config is usable."""

    execution_family: str
    contract_status: str
    reason_code: str | None

    @property
    def complete(self) -> bool:
        return self.contract_status == "complete" and self.reason_code is None


def inspect_agentic_family_readiness(
    *,
    definition,
    binding,
    registry,
    store=None,
) -> AgenticFamilyReadiness:
    """Check executable presence and direct provider/adapter compatibility."""
    family = effective_agentic_execution_family(
        getattr(definition, "execution_family", "") or "",
        runtime_engine_id=definition.runtime_engine_id,
        adapter_id=definition.adapter_id,
        model_provider_id=definition.model_provider_id,
        provider_protocol=definition.provider_protocol,
    )
    if family == NATIVE_AGENT_EXECUTION_FAMILY:
        return _native_readiness(definition=definition, registry=registry)
    if family == MAVERICK_AGENT_EXECUTION_FAMILY:
        return AgenticFamilyReadiness(family, "complete", None)
    return AgenticFamilyReadiness(family, "incomplete", "execution_family_unclassified")


def _native_readiness(*, definition, registry) -> AgenticFamilyReadiness:
    try:
        installation = registry.get_native_agent_installation(
            definition.runtime_engine_id
        )
    except ProviderNotFoundError:
        return AgenticFamilyReadiness(
            NATIVE_AGENT_EXECUTION_FAMILY,
            "incomplete",
            "native_agent_installation_missing",
        )
    manifest = installation.manifest
    if (
        manifest.runtime_engine_id != definition.runtime_engine_id
        or manifest.adapter_id != definition.adapter_id
        or definition.adapter_version_constraint != f"=={manifest.adapter_version}"
        or manifest.protocol_id != definition.provider_protocol
        or not manifest.machine_readable
        or manifest.human_terminal_scraping
        or not native_agent_model_provider_connected(
            installation,
            model_provider_id=definition.model_provider_id,
        )
    ):
        return AgenticFamilyReadiness(
            NATIVE_AGENT_EXECUTION_FAMILY,
            "incomplete",
            "native_agent_contract_incomplete",
        )
    status = installation.inspector.inspect()
    if status.availability != "installed" or status.health not in {
        "healthy",
        "degraded",
    }:
        return AgenticFamilyReadiness(
            NATIVE_AGENT_EXECUTION_FAMILY,
            "incomplete",
            "native_runtime_unavailable",
        )
    return AgenticFamilyReadiness(NATIVE_AGENT_EXECUTION_FAMILY, "complete", None)


__all__ = ["AgenticFamilyReadiness", "inspect_agentic_family_readiness"]
