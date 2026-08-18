"""Maverick-owned Codex reasoning defaults and catalog normalization."""

from __future__ import annotations

from dataclasses import replace

from core.providers.models import ProviderModelOption


CODEX_DEFAULT_REASONING_EFFORT = "max"
CODEX_MULTI_AGENT_EFFORTS = frozenset({"ultra"})
CODEX_REASONING_PREFERENCE = ("max", "xhigh", "high", "medium", "low", "minimal")


def codex_default_reasoning_effort(option: ProviderModelOption | None) -> str | None:
    """Choose Maverick's deepest single-agent reasoning effort for one Codex model."""
    if option is None:
        return CODEX_DEFAULT_REASONING_EFFORT
    supported = [
        reasoning.effort
        for reasoning in option.supported_reasoning_efforts
        if reasoning.effort not in CODEX_MULTI_AGENT_EFFORTS
    ]
    if not supported:
        return None
    for effort in CODEX_REASONING_PREFERENCE:
        if effort in supported:
            return effort
    if option.default_reasoning_effort in supported:
        return option.default_reasoning_effort
    return supported[-1]


def normalize_codex_model_option(option: ProviderModelOption) -> ProviderModelOption:
    """Remove multi-agent modes from reasoning and apply the single-agent maximum."""
    reasoning_options = [
        reasoning
        for reasoning in option.supported_reasoning_efforts
        if reasoning.effort not in CODEX_MULTI_AGENT_EFFORTS
    ]
    normalized = replace(option, supported_reasoning_efforts=reasoning_options)
    return replace(
        normalized,
        default_reasoning_effort=codex_default_reasoning_effort(normalized),
    )


def normalize_codex_model_options(options: list[ProviderModelOption]) -> list[ProviderModelOption]:
    """Normalize every Codex model option without mutating provider-owned input."""
    return [normalize_codex_model_option(option) for option in options]
