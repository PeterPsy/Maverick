from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
import os
import unittest
from unittest.mock import patch

from core.api.platform_state import bootstrap_platform_state
from core.providers.certificate_projection import certificate_profile_status
from core.providers.agentic_profiles import (
    CODEX_PROFILE_REVISION,
    publish_codex_agentic_profile,
)
from core.providers.builtin_certification import ensure_codex_preview_certificate
from core.providers.execution_family_readiness import (
    inspect_agentic_family_readiness,
)
from core.providers.native_agent_contract import NativeRuntimeStatus
from core.providers.native_agent_status import native_agent_status_items
from tests.support.repo import make_temp_repo_root


NOW = datetime(2026, 8, 24, tzinfo=UTC)


class AgenticCatalogBootstrapTest(unittest.TestCase):
    def test_migration_certifies_every_model_from_persisted_codex_catalog(self) -> None:
        root = make_temp_repo_root(self)
        with patch.dict(
            os.environ,
            {"MAVERICK_ALLOW_INSECURE_TEST_DEFAULTS": "1"},
            clear=False,
        ):
            initial = bootstrap_platform_state(
                start_path=root,
                now=NOW,
                install_builtin_apps=False,
            )
            codex = initial.provider_store.get_provider_definition("codex")
            base_model = codex.model_options[0]
            persisted_models = [
                base_model,
                replace(base_model, model_id="gpt-6-astra", label="GPT-6 Astra"),
                replace(base_model, model_id="catalog-model-three", label="Catalog model three"),
            ]
            initial.provider_store.save_provider_definition(
                replace(codex, model_options=persisted_models)
            )

            restarted = bootstrap_platform_state(
                start_path=root,
                now=NOW,
                install_builtin_apps=False,
            )

        effective_codex = restarted.provider_registry.get_provider_definition("codex")
        self.assertEqual(
            {model.model_id for model in effective_codex.model_options},
            {model.model_id for model in persisted_models},
        )
        adapter = restarted.provider_registry.get_agentic_runtime_adapter("codex")
        current_profiles = {
            profile.model_id: profile
            for profile in restarted.provider_store.list_agentic_profile_definitions()
            if profile.runtime_engine_id == "codex"
            and profile.revision == CODEX_PROFILE_REVISION
        }
        self.assertEqual(set(current_profiles), {model.model_id for model in persisted_models})
        for model_id, profile in current_profiles.items():
            certificate = restarted.provider_store.get_capability_certificate(
                profile.capability_certificate_id
            )
            status = restarted.provider_store.get_capability_certificate_status(
                certificate.certificate_id
            )
            self.assertEqual(
                certificate_profile_status(
                    certificate,
                    status,
                    definition=profile,
                    adapter=adapter,
                    now=NOW,
                ),
                "active",
                model_id,
            )
            readiness = inspect_agentic_family_readiness(
                definition=profile,
                certificate=certificate,
                binding=None,
                registry=restarted.provider_registry,
            )
            self.assertTrue(readiness.complete, (model_id, readiness.reason_code))

        unknown_profile = publish_codex_agentic_profile(
            restarted.provider_store,
            definition=effective_codex,
            model_id="not-in-codex-catalog",
            now=NOW,
        )
        unknown_certificate = ensure_codex_preview_certificate(
            restarted.provider_store,
            definition=unknown_profile,
            provider_definition=effective_codex,
            adapter=adapter,
        )
        unknown_readiness = inspect_agentic_family_readiness(
            definition=unknown_profile,
            certificate=unknown_certificate,
            binding=None,
            registry=restarted.provider_registry,
        )
        self.assertFalse(unknown_readiness.complete)
        self.assertEqual(
            unknown_readiness.reason_code,
            "native_agent_model_unavailable",
        )

        installation = restarted.provider_registry.get_native_agent_installation(
            "codex"
        )
        healthy = NativeRuntimeStatus(
            availability="installed",
            executable_path="/usr/local/bin/codex",
            runtime_version="codex-cli 0.153.4",
            health="healthy",
            reason_codes=(),
            update_status="current",
        )
        with patch.object(installation.inspector, "inspect", return_value=healthy):
            native = next(
                item
                for item in native_agent_status_items(restarted.provider_registry)
                if item["runtime_engine_id"] == "codex"
            )
        self.assertEqual(
            {model["model_id"] for model in native["models"]},
            {model.model_id for model in persisted_models},
        )


if __name__ == "__main__":
    unittest.main()
