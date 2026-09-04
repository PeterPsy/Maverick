"""Phase-5 UI taxonomy, readiness, and safe selection migration tests."""

from __future__ import annotations

from dataclasses import replace
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from core.api.provider_api import (
    workspace_agentic_admin_status,
    workspace_provider_status,
)
from core.providers.native_agent_contract import NativeRuntimeStatus
from core.providers.service import (
    builtin_provider_registry,
    configure_workspace_provider,
    register_builtin_providers,
)
from core.providers.store import ProviderCollections, ProviderDocumentStore
from tests.support.collections import FakeCollection


class ProviderExecutionFamilyApiTest(unittest.TestCase):
    def make_state(self):
        store = ProviderDocumentStore(
            ProviderCollections(
                definitions=FakeCollection(),
                bindings=FakeCollection(),
                selections=FakeCollection(),
            )
        )
        registry = builtin_provider_registry(refresh_model_catalog=False)
        register_builtin_providers(store, registry=registry)
        configure_workspace_provider(
            store,
            workspace_id="default",
            provider_id="codex",
            registry=registry,
        )
        return SimpleNamespace(
            provider_store=store,
            provider_registry=registry,
            secret_store=None,
            workspace_store=SimpleNamespace(get_governance=lambda _workspace_id: None),
        )

    def test_catalog_and_codex_use_the_exact_certified_native_family(self) -> None:
        state = self.make_state()
        payload = workspace_provider_status(state, workspace_id="default")

        self.assertEqual(
            [item["family_id"] for item in payload["execution_families"]],
            ["native_agent", "maverick_agent", "hosted_text"],
        )
        self.assertEqual(
            [item["label"] for item in payload["execution_families"]],
            [
                "Native Agents (CLI)",
                "Maverick Agents (API)",
                "Text-only Models (API)",
            ],
        )
        self.assertEqual(
            [item["description"] for item in payload["execution_families"]],
            [
                "External coding-agent runtimes such as Codex, Claude Code, and "
                "Gemini CLI. They use their own agent loop and tools, while "
                "Maverick launches, connects to, and supervises them.",
                "API models made agentic by Maverick. Maverick provides workspace "
                "context, tools, the execution loop, approvals, finalization, and "
                "recovery.",
                "API models without workspace tools or an action loop. They "
                "generate text from the context provided by Maverick but cannot "
                "perform workspace actions.",
            ],
        )
        profile = payload["agentic_profiles"]["items"][0]
        self.assertEqual(profile["execution_family"], "native_agent")
        self.assertEqual(profile["full_workspace_status"], "certified")
        self.assertEqual(
            profile["full_workspace_contract_revision"],
            "codex-baseline-v20",
        )
        self.assertEqual(profile["harness_recipe"]["id"], "codex-native-app-server")
        self.assertTrue(profile["selectable"])
        admin = workspace_agentic_admin_status(state, workspace_id="default")["items"][0]
        self.assertTrue(admin["supported_reasoning_efforts"])
        self.assertIn(
            admin["default_reasoning_effort"],
            [item["effort"] for item in admin["supported_reasoning_efforts"]],
        )
        self.assertEqual(admin["full_workspace_status"], "certified")
        self.assertEqual(admin["native_runtime"]["health"], "healthy")
        self.assertTrue(admin["enable_eligible"])
        self.assertIsNone(admin["enable_blocked_reason"])

    def test_disabled_complete_profile_remains_eligible_for_reenable(self) -> None:
        state = self.make_state()
        binding = state.provider_store.list_workspace_agentic_profile_bindings(
            "default"
        )[0]
        state.provider_store.save_workspace_agentic_profile_binding(
            replace(
                binding,
                enabled=False,
                is_default=False,
                revision=binding.revision + 1,
            ),
            expected_revision=binding.revision,
        )

        item = workspace_agentic_admin_status(state, workspace_id="default")["items"][0]

        self.assertFalse(item["selectable"])
        self.assertEqual(item["blocked_reason"], "workspace_binding_disabled")
        self.assertTrue(item["enable_eligible"])
        self.assertIsNone(item["enable_blocked_reason"])

    def test_missing_live_authority_is_never_reported_as_selectable(self) -> None:
        state = self.make_state()
        state.workspace_store = SimpleNamespace()

        profile = workspace_provider_status(
            state,
            workspace_id="default",
        )["agentic_profiles"]["items"][0]

        self.assertFalse(profile["selectable"])
        self.assertEqual(profile["unavailable_reason"], "runtime_authority_unavailable")
        self.assertEqual(profile["effective_capabilities"]["status"], "blocked")

    def test_uncertified_native_candidate_is_visible_but_never_selectable(self) -> None:
        payload = workspace_provider_status(self.make_state(), workspace_id="default")
        candidates = {
            item["runtime_engine_id"]: item
            for item in payload["native_agents"]["items"]
        }

        gemini = candidates["gemini-cli"]
        self.assertFalse(gemini["selectable"])
        self.assertEqual(gemini["provider_status"], "disabled")
        self.assertEqual(gemini["full_workspace_status"], "unavailable")
        self.assertEqual(gemini["unavailable_reason"], "native_agent_certificate_incomplete")
        self.assertNotIn("executable_path", gemini)

    def test_certified_native_profile_is_unavailable_when_runtime_is_missing(self) -> None:
        state = self.make_state()
        inspector = state.provider_registry.get_native_agent_installation(
            "codex"
        ).inspector
        missing = NativeRuntimeStatus(
            availability="not_installed",
            executable_path=None,
            runtime_version=None,
            health="unavailable",
            reason_codes=("runtime_not_installed",),
            update_status="unknown",
        )

        with patch.object(inspector, "inspect", return_value=missing):
            payload = workspace_provider_status(state, workspace_id="default")
            admin = workspace_agentic_admin_status(state, workspace_id="default")

        profile = payload["agentic_profiles"]["items"][0]
        self.assertEqual(profile["family_contract_status"], "complete")
        self.assertEqual(profile["full_workspace_status"], "certified")
        self.assertFalse(profile["selectable"])
        self.assertEqual(profile["unavailable_reason"], "native_runtime_not_installed")
        self.assertFalse(admin["items"][0]["selectable"])
        self.assertEqual(admin["items"][0]["blocked_reason"], "native_runtime_not_installed")
        self.assertFalse(admin["items"][0]["enable_eligible"])
        self.assertEqual(
            admin["items"][0]["enable_blocked_reason"],
            "native_runtime_not_installed",
        )

    def test_native_inspection_failure_is_redacted_and_fail_closed(self) -> None:
        state = self.make_state()
        inspector = state.provider_registry.get_native_agent_installation(
            "codex"
        ).inspector

        with patch.object(inspector, "inspect", side_effect=RuntimeError("secret path")):
            payload = workspace_provider_status(state, workspace_id="default")

        native = next(
            item
            for item in payload["native_agents"]["items"]
            if item["runtime_engine_id"] == "codex"
        )
        profile = payload["agentic_profiles"]["items"][0]
        self.assertEqual(native["health_reason_codes"], ("runtime_inspection_failed",))
        self.assertEqual(native["unavailable_reason"], "runtime_inspection_failed")
        self.assertNotIn("secret path", str(native))
        self.assertFalse(profile["selectable"])
        self.assertEqual(profile["unavailable_reason"], "runtime_inspection_failed")

    def test_narrowed_agent_binding_is_not_selectable_as_a_partial_agent(self) -> None:
        for mode in ("none", "exact"):
            with self.subTest(tool_handle_mode=mode):
                state = self.make_state()
                binding = state.provider_store.list_workspace_agentic_profile_bindings(
                    "default"
                )[0]
                narrowed = replace(
                    binding,
                    workspace_policy_ceiling=replace(
                        binding.workspace_policy_ceiling,
                        tool_handle_mode=mode,
                        allowed_tool_handles=(),
                    ),
                    revision=binding.revision + 1,
                )
                state.provider_store.save_workspace_agentic_profile_binding(
                    narrowed,
                    expected_revision=binding.revision,
                )

                payload = workspace_provider_status(state, workspace_id="default")
                profile = payload["agentic_profiles"]["items"][0]

                self.assertFalse(profile["selectable"])
                self.assertEqual(profile["full_workspace_status"], "unavailable")
                self.assertEqual(
                    profile["unavailable_reason"],
                    "full_workspace_policy_incomplete",
                )
                self.assertIsNone(payload["agentic_profiles"]["default_binding_id"])
                admin = workspace_agentic_admin_status(
                    state,
                    workspace_id="default",
                )["items"][0]
                self.assertFalse(admin["enable_eligible"])
                self.assertEqual(
                    admin["enable_blocked_reason"],
                    "full_workspace_policy_incomplete",
                )

    def test_text_profiles_have_a_separate_no_actions_certificate(self) -> None:
        payload = workspace_provider_status(self.make_state(), workspace_id="default")
        hosted = payload["hosted_text"]

        self.assertEqual(
            hosted["workspace_actions_message"],
            "No workspace tools or actions.",
        )
        self.assertTrue(hosted["profiles"])
        for item in hosted["profiles"]:
            self.assertEqual(item["profile"]["execution_family"], "hosted_text")
            self.assertEqual(
                item["certificate"]["certificate_kind"],
                "hosted_text_capability",
            )
            self.assertFalse(item["certificate"]["workspace_tools"])
            self.assertFalse(item["certificate"]["action_loop"])
            self.assertFalse(item["certificate"]["workspace_actions"])

    def test_legacy_selection_migration_is_projection_only(self) -> None:
        state = self.make_state()
        before = state.provider_store.get_provider_selection("default")

        payload = workspace_provider_status(state, workspace_id="default")

        self.assertEqual(state.provider_store.get_provider_selection("default"), before)
        migration = payload["selection_migration"]
        self.assertEqual(migration["mode"], "projection_only")
        self.assertFalse(migration["persisted_records_mutated"])
        self.assertFalse(migration["pinned_sessions_rewritten"])
        self.assertEqual(migration["records"][0]["execution_family"], "native_agent")
        self.assertEqual(migration["records"][0]["storage_action"], "preserved")


if __name__ == "__main__":
    unittest.main()
