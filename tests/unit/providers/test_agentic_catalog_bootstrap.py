"""Fresh runtime discovery, not persisted metadata, publishes native models."""

from dataclasses import replace
from datetime import UTC, datetime
import os
import unittest
from unittest.mock import patch

from core.api.platform_state import bootstrap_platform_state
from core.providers.certificate_service import runtime_adapter_artifact_digest
from core.providers.agentic_profiles import CODEX_PROFILE_ARTIFACT_DIGEST
from core.providers.execution_family_readiness import inspect_agentic_family_readiness
from core.providers.service import effective_provider_registry
from tests.support.native_agent_catalog import codex_snapshot
from tests.support.repo import make_temp_repo_root


class AgenticCatalogBootstrapTest(unittest.TestCase):
    def test_live_refresh_publishes_all_models_without_a_restart(self):
        root = make_temp_repo_root(self)
        with patch.dict(os.environ, {"MAVERICK_ALLOW_INSECURE_TEST_DEFAULTS": "1"}), patch(
            "core.providers.native_agent_reconciliation.discover_codex_native_catalog",
            return_value=codex_snapshot("gpt-5.6-sol"),
        ) as discover:
            state = bootstrap_platform_state(start_path=root, now=datetime.now(tz=UTC), install_builtin_apps=False)
            initial = len(state.provider_store.list_capability_certificates())
            discover.return_value = codex_snapshot("gpt-5.6-sol", "new-advertised-model")
            effective_provider_registry(state.provider_store, registry=state.provider_registry, refresh_model_catalog=True)
            profiles = state.provider_store.list_agentic_profile_definitions()
            profile = next(item for item in profiles if item.model_id == "new-advertised-model")
            certificate = state.provider_store.get_capability_certificate(profile.capability_certificate_id)
            self.assertEqual(len(state.provider_store.list_capability_certificates()), initial + 1)
            self.assertTrue(inspect_agentic_family_readiness(
                definition=profile, certificate=certificate, binding=None,
                registry=state.provider_registry, store=state.provider_store,
            ).complete)
            evidence = state.provider_store.get_capability_evidence(certificate.evidence_digest)
            restarted = bootstrap_platform_state(start_path=root, install_builtin_apps=False)
            self.assertEqual(restarted.provider_store.get_capability_evidence(certificate.evidence_digest), evidence)
            self.assertEqual(runtime_adapter_artifact_digest(restarted.provider_registry.get_runtime_adapter("codex")), CODEX_PROFILE_ARTIFACT_DIGEST)

    def test_persisted_models_and_fallback_are_not_authority(self):
        root = make_temp_repo_root(self)
        with patch.dict(os.environ, {"MAVERICK_ALLOW_INSECURE_TEST_DEFAULTS": "1"}), patch(
            "core.providers.native_agent_reconciliation.discover_codex_native_catalog",
            return_value=codex_snapshot("gpt-5.6-sol"),
        ) as discover:
            state = bootstrap_platform_state(start_path=root, install_builtin_apps=False)
            definition = state.provider_store.get_provider_definition("codex")
            state.provider_store.save_provider_definition(replace(definition, model_options=[
                *definition.model_options, replace(definition.model_options[0], model_id="persisted-injection"),
            ]))
            discover.return_value = None
            restarted = bootstrap_platform_state(start_path=root, install_builtin_apps=False)
            self.assertIsNone(restarted.provider_registry.get_native_agent_catalog("codex", "codex"))
            self.assertFalse(any(item.model_id == "persisted-injection" and item.native_connection_certificate_id
                                 for item in restarted.provider_store.list_capability_certificates()))


if __name__ == "__main__":
    unittest.main()
