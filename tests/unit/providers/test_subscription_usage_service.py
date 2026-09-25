"""Provider-neutral subscription usage service tests."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import patch
import unittest

from core.providers.models import (
    ProviderCapabilitySet,
    ProviderDefinition,
    ProviderSubscriptionUsage,
)
from core.providers.provider_registry import ProviderRegistry
from core.providers.service import read_workspace_provider_subscription_usage


class UsageAdapter:
    def __init__(self, provider_id: str) -> None:
        self.runtime_engine_id = provider_id

    def read_subscription_usage(self) -> ProviderSubscriptionUsage:
        return ProviderSubscriptionUsage(
            provider_id=self.runtime_engine_id,
            provider_label=self.runtime_engine_id,
            available=True,
            fetched_at=datetime(2026, 9, 25, tzinfo=UTC),
        )


def definition(provider_id: str, *, supports_usage: bool) -> ProviderDefinition:
    timestamp = datetime(2026, 9, 25, tzinfo=UTC)
    return ProviderDefinition(
        provider_id=provider_id,
        label=provider_id,
        description=provider_id,
        kind="runtime_backend",
        provider_role="runtime_engine",
        status="active",
        capabilities=ProviderCapabilitySet(
            supports_interactive_runtime=True,
            supports_streaming=True,
            supports_tools=True,
            supports_mcp=True,
            supports_skills=True,
            supports_filesystem_access=True,
            supports_remote_execution=False,
            supports_api_key_auth=False,
            supports_local_binary=True,
            supports_subscription_usage=supports_usage,
        ),
        default_model_family=None,
        requires_credentials=False,
        supported_execution_modes=["sandbox"],
        created_at=timestamp,
        updated_at=timestamp,
    )


class SubscriptionUsageServiceTest(unittest.TestCase):
    def test_reads_every_usage_capable_provider_not_only_the_active_one(self) -> None:
        registry = ProviderRegistry()
        for provider_id in ("codex", "antigravity-cli"):
            provider_definition = definition(provider_id, supports_usage=True)
            registry.register_provider_definition(provider_definition)
            registry.register_agentic_runtime_adapter(
                UsageAdapter(provider_id),  # type: ignore[arg-type]
                definition=provider_definition,
            )
        registry.register_provider_definition(definition("openrouter", supports_usage=False))

        with patch(
            "core.providers.service.effective_provider_registry",
            return_value=registry,
        ):
            usages = read_workspace_provider_subscription_usage(
                object(),  # type: ignore[arg-type]
                workspace_id="default",
                now=datetime(2026, 9, 25, tzinfo=UTC),
            )

        self.assertEqual(
            [usage.provider_id for usage in usages],
            ["antigravity-cli", "codex"],
        )


if __name__ == "__main__":
    unittest.main()
