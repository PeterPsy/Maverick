"""Provider schema tests for role-aware provider metadata."""

from __future__ import annotations

from datetime import UTC, datetime
import unittest

from core.providers.models import (
    ProviderCapabilitySet,
    ProviderCredentialRequirement,
    ProviderDefinition,
    ProviderExecutionContract,
    ProviderModelOption,
    ProviderNetworkRequirement,
)
from core.providers.provider_codex import build_codex_definition
from core.providers.store import ProviderCollections, ProviderDocumentStore
from tests.support.collections import FakeCollection


class ProviderSchemaTest(unittest.TestCase):
    def make_store(self) -> ProviderDocumentStore:
        return ProviderDocumentStore(
            ProviderCollections(
                definitions=FakeCollection(),
                bindings=FakeCollection(),
                selections=FakeCollection(),
            )
        )

    def test_codex_definition_is_explicit_runtime_engine(self) -> None:
        definition = build_codex_definition()

        self.assertEqual(definition.kind, "runtime_backend")
        self.assertEqual(definition.provider_role, "runtime_engine")
        self.assertIn("text", definition.capabilities.input_modalities)
        self.assertIn("events", definition.capabilities.output_modalities)
        self.assertTrue(definition.capabilities.supports_tool_calling)

    def test_store_hydrates_legacy_provider_definition_with_inferred_role(self) -> None:
        store = self.make_store()
        now = datetime(2026, 6, 22, 12, 0, tzinfo=UTC)
        store.collections.definitions.documents.append(
            {
                "provider_id": "legacy-hosted",
                "label": "Legacy Hosted",
                "description": "Legacy hosted provider without provider_role.",
                "kind": "hosted_api",
                "status": "active",
                "capabilities": {
                    "supports_interactive_runtime": False,
                    "supports_streaming": True,
                    "supports_tools": False,
                    "supports_mcp": False,
                    "supports_skills": False,
                    "supports_filesystem_access": False,
                    "supports_remote_execution": True,
                    "supports_api_key_auth": True,
                    "supports_local_binary": False,
                },
                "default_model_family": "fast-text",
                "requires_credentials": True,
                "supported_execution_modes": [],
                "created_at": now,
                "updated_at": now,
                "model_options": [],
            }
        )

        definition = store.get_provider_definition("legacy-hosted")

        self.assertEqual(definition.provider_role, "model_provider")
        self.assertEqual(definition.capabilities.input_modalities, [])
        self.assertFalse(definition.capabilities.supports_realtime)

    def test_model_provider_metadata_round_trips_without_secret_values(self) -> None:
        store = self.make_store()
        now = datetime(2026, 6, 22, 12, 0, tzinfo=UTC)
        definition = ProviderDefinition(
            provider_id="groq",
            label="Groq",
            description="Hosted low-latency text model provider.",
            kind="hosted_api",
            status="experimental",
            capabilities=ProviderCapabilitySet(
                supports_interactive_runtime=False,
                supports_streaming=True,
                supports_tools=False,
                supports_mcp=False,
                supports_skills=False,
                supports_filesystem_access=False,
                supports_remote_execution=True,
                supports_api_key_auth=True,
                supports_local_binary=False,
                input_modalities=["text"],
                output_modalities=["text"],
                supports_streaming_output=True,
                supports_tool_calling=False,
                latency_class="low",
            ),
            default_model_family="llama-3.3-70b-versatile",
            requires_credentials=True,
            supported_execution_modes=[],
            created_at=now,
            updated_at=now,
            model_options=[
                ProviderModelOption(
                    model_id="llama-3.3-70b-versatile",
                    label="Llama 3.3 70B Versatile",
                    description="Hosted text model.",
                    default_reasoning_effort=None,
                )
            ],
            provider_role="model_provider",
            credential_requirements=[
                ProviderCredentialRequirement(
                    secret_alias_or_logical_name="groq_api_key",
                    secret_kind="api_key",
                    required_for_modes=["plain_hosted_chat"],
                    secret_binding_scope="provider",
                    provider_credential_binding_id_optional="provider-groq-binding",
                )
            ],
            network_requirements=[
                ProviderNetworkRequirement(
                    outbound_required=True,
                    allowed_hosts=["api.groq.com"],
                    transport="https",
                )
            ],
            execution_contract=ProviderExecutionContract(
                adapter_type="hosted_text_generation",
                request_shape="chat_messages",
                streaming_supported=True,
                non_streaming_supported=True,
                timeout_policy="short_interactive",
                secret_alias_or_logical_name="groq_api_key",
                transport_test_mode="fake_supported",
            ),
            latency_metadata={"latency_class": "low"},
        )

        store.save_provider_definition(definition)
        reloaded = store.get_provider_definition("groq")

        self.assertEqual(reloaded.provider_role, "model_provider")
        self.assertEqual(reloaded.credential_requirements[0].secret_alias_or_logical_name, "groq_api_key")
        self.assertTrue(reloaded.credential_requirements[0].redaction_required)
        self.assertEqual(reloaded.credential_requirements[0].resolution_stage, "execution_only")
        self.assertEqual(reloaded.network_requirements[0].allowed_hosts, ["api.groq.com"])
        self.assertIsNotNone(reloaded.execution_contract)
        self.assertEqual(reloaded.execution_contract.adapter_type, "hosted_text_generation")
        self.assertFalse(hasattr(reloaded.credential_requirements[0], "secret_value"))


if __name__ == "__main__":
    unittest.main()
