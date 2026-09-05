"""Explicit trusted discovery observations for native control-plane tests."""

from dataclasses import replace
from datetime import UTC, datetime, timedelta

from core.providers.native_agent_catalog import NativeAgentCatalogModel, NativeAgentCatalogSnapshot
from core.providers.provider_codex_models import build_codex_definition


def codex_snapshot(*model_ids, reasoning=("low", "medium", "high", "xhigh", "max"), revision=None):
    from core.providers.models import ProviderReasoningOption

    now = datetime.now(tz=UTC)
    base = build_codex_definition().model_options[0]
    models = tuple(NativeAgentCatalogModel(
        model_provider_id="codex", model_id=model_id, model_revision=revision,
        revision_policy="exact" if revision else "provider_alias",
        reasoning_efforts=reasoning, default_reasoning_effort=reasoning[-1] if reasoning else None,
    ) for model_id in model_ids)
    options = tuple(replace(base, model_id=model.model_id, label=model.model_id,
        default_reasoning_effort=model.default_reasoning_effort,
        supported_reasoning_efforts=[ProviderReasoningOption(effort=value, label=value) for value in reasoning],
        metadata={"model_revision": revision, "model_revision_policy": model.revision_policy,
                  "native_model_catalog_digest": model.digest},
    ) for model in models)
    return NativeAgentCatalogSnapshot("codex", "codex", "codex", "trusted-test-cli", now,
                                      now + timedelta(minutes=5), models, options)
