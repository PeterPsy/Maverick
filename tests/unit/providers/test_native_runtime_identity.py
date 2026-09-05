"""Native artifact swaps and exact revisions cannot cross the launch boundary."""

import asyncio
from dataclasses import replace
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch

from core.providers.agentic_models import default_actor_selection_policy
from core.providers.agentic_profiles import build_pinned_execution_binding
from core.providers.agentic_workspace_admin import save_workspace_agentic_binding
from core.providers.certificate_service import validate_certificate_for_binding
from core.providers.errors import AgenticProfileError, CapabilityCertificateError
from core.providers.native_agent_reconciliation import refresh_codex_native_catalog
from core.providers.native_runtime_artifact import inspect_native_runtime_artifact
from core.providers.service import builtin_provider_registry, effective_provider_registry
from tests.support.maverick_agent_onboarding import provider_store


class NativeRuntimeIdentityTest(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.command = Path(folder.name) / "fixture-codex"
        self.write_binary("one")
        approved = inspect_native_runtime_artifact(str(self.command))
        self.store = provider_store()
        with patch("core.providers.native_agent_builtins.CODEX_PACKAGED_RUNTIME_ARTIFACT", approved):
            self.registry = effective_provider_registry(
                self.store, registry=builtin_provider_registry(codex_command=str(self.command)),
            )
        profile = next(item for item in self.store.list_agentic_profile_definitions() if item.model_id == "fixture-model")
        self.binding = save_workspace_agentic_binding(
            self.store, self.registry, workspace_id="default", definition_id=profile.definition_id,
            definition_revision=profile.revision, credential_binding_id=None, enabled=True,
            is_default=True, actor_policy=default_actor_selection_policy(), policy_patch={},
        )
        self.adapter = self.registry.get_agentic_runtime_adapter("codex")
        self.pin = self.new_pin()

    def write_binary(self, version):
        self.command.write_text(
            f'#!/bin/sh\nif [ "$1" = "--version" ]; then echo "codex-fixture {version}"; exit 0; fi\n'
            'echo \'{"models":[{"slug":"fixture-model","visibility":"list"}]}\'\n'
        )
        self.command.chmod(0o755)

    def new_pin(self):
        return build_pinned_execution_binding(
            self.store, self.registry, session_id="pin", workspace_id="default", execution_mode="sandbox",
        )

    def test_runtime_replacement_fences_new_pins_existing_authority_and_launch(self):
        before = self.store.list_capability_certificates()
        self.write_binary("two")
        refresh_codex_native_catalog(self.registry, store=self.store, force=True)
        with self.assertRaisesRegex(AgenticProfileError, "native_runtime_artifact_mismatch"):
            self.new_pin()
        with self.assertRaisesRegex(CapabilityCertificateError, "native_runtime_artifact_mismatch"):
            validate_certificate_for_binding(self.store, binding=self.pin, adapter=self.adapter)
        with patch.object(self.adapter.engine_adapter, "build_launch_spec", new_callable=AsyncMock) as launch:
            with self.assertRaisesRegex(CapabilityCertificateError, "native_runtime_artifact_mismatch"):
                asyncio.run(self.adapter.launch(SimpleNamespace(binding=self.pin)))
            launch.assert_not_called()
        self.assertEqual(self.store.list_capability_certificates(), before)

    def test_exact_legacy_pin_fails_before_launch_connect_and_resume(self):
        exact = replace(self.pin, model_revision="revision-one", model_revision_policy="exact")
        with self.assertRaisesRegex(CapabilityCertificateError, "native_agent_exact_revision_unsupported"):
            validate_certificate_for_binding(self.store, binding=exact, adapter=self.adapter)
        for operation in (self.adapter.launch, self.adapter.connect, self.adapter.resume):
            with self.subTest(operation=operation.__name__), self.assertRaisesRegex(
                CapabilityCertificateError, "native_agent_exact_revision_unsupported",
            ):
                asyncio.run(operation(SimpleNamespace(binding=exact)))


if __name__ == "__main__":
    unittest.main()
