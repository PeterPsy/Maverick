"""Credential delivery for engine-owned native process launch specs."""

from datetime import UTC, datetime
from types import SimpleNamespace
import unittest

from core.providers.models import (
    ProviderCapabilitySet,
    ProviderDefinition,
    ProviderSelection,
    RuntimeBackendLaunchSpec,
)
from core.providers.provider_credentials import bind_provider_credential
from core.providers.service import build_resolved_runtime_backend_launch_spec
from core.providers.store import ProviderCollections, ProviderDocumentStore
from core.secrets.service import create_platform_secret
from core.secrets.store import SecretCollections, SecretDocumentStore
from tests.support.collections import FakeCollection


class _CapturingAgenticAdapter:
    def __init__(self) -> None:
        self.context = None

    async def build_launch_spec(self, context) -> RuntimeBackendLaunchSpec:
        self.context = context
        return RuntimeBackendLaunchSpec(
            provider_id="credentialed-native",
            command=["native-fixture"],
            env_overrides=dict(context.secret_env),
            credential_binding_id=None,
            resolved_secret_refs=[],
            working_directory=context.session.workdir,
            execution_mode=context.session.effective_mode,
            readable_roots=[context.session.workspace_root],
            writable_roots=[context.session.workspace_root],
        )


class AgenticLaunchSecretResolutionTest(unittest.TestCase):
    def test_platform_secret_reaches_async_native_builder_and_metadata(self) -> None:
        provider_store = ProviderDocumentStore(
            ProviderCollections(
                definitions=FakeCollection(),
                bindings=FakeCollection(),
                selections=FakeCollection(),
            )
        )
        secret_store = SecretDocumentStore(
            SecretCollections(
                secrets=FakeCollection(),
                values=FakeCollection(),
                bindings=FakeCollection(),
                grants=FakeCollection(),
            )
        )
        credential = bind_provider_credential(
            provider_store,
            provider_id="credentialed-native",
            secret_ref="platform:secret-alias/credentialed-native",
            workspace_id="default",
        )
        create_platform_secret(
            secret_store,
            label="Native provider fixture",
            raw_value="fixture-native-secret",
            alias="credentialed-native",
        )
        timestamp = datetime.now(tz=UTC)
        definition = ProviderDefinition(
            provider_id="credentialed-native",
            label="Credentialed native",
            description="Fixture engine-owned process.",
            kind="runtime_backend",
            provider_role="runtime_engine",
            status="active",
            capabilities=ProviderCapabilitySet(
                supports_interactive_runtime=True,
                supports_streaming=True,
                supports_tools=True,
                supports_mcp=False,
                supports_skills=False,
                supports_filesystem_access=True,
                supports_remote_execution=False,
                supports_api_key_auth=True,
                supports_local_binary=True,
            ),
            default_model_family="fixture-model",
            requires_credentials=True,
            supported_execution_modes=["sandbox"],
            created_at=timestamp,
            updated_at=timestamp,
        )
        selection = ProviderSelection(
            selection_id="selection",
            workspace_id="default",
            provider_id="credentialed-native",
            binding_id=credential.binding_id,
            selection_scope="workspace_default",
            selection_reason="fixture",
            created_at=timestamp,
            updated_at=timestamp,
            model_id="fixture-model",
        )
        execution_binding = SimpleNamespace(
            credential_binding_id=credential.binding_id,
            model_id="fixture-model",
        )
        session = SimpleNamespace(
            session_id="session",
            workspace_id="default",
            workspace_root="/workspace",
            workdir="/workspace",
            effective_mode="sandbox",
            execution_binding=execution_binding,
        )
        adapter = _CapturingAgenticAdapter()

        spec = build_resolved_runtime_backend_launch_spec(
            provider_store,
            session=session,
            definition=definition,
            selection=selection,
            agentic_adapter=adapter,
            secret_store=secret_store,
        )

        self.assertIs(adapter.context.session, session)
        self.assertIs(adapter.context.binding, execution_binding)
        self.assertEqual(
            adapter.context.secret_env,
            {"MAVERICK_PROVIDER_SECRET": "fixture-native-secret"},
        )
        self.assertEqual(
            spec.env_overrides,
            {"MAVERICK_PROVIDER_SECRET": "fixture-native-secret"},
        )
        self.assertEqual(spec.credential_binding_id, credential.binding_id)
        self.assertEqual(
            spec.resolved_secret_refs,
            ["platform:secret-alias/credentialed-native"],
        )


if __name__ == "__main__":
    unittest.main()
