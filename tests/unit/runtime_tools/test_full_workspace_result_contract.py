from __future__ import annotations

from dataclasses import replace
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from core.providers.agentic_models import codex_runtime_policy
from core.providers.capability_models import RuntimeCapabilitySet
from core.providers.errors import CapabilityCertificateError
from core.runtime.full_workspace_contract import (
    FULL_WORKSPACE_CONTRACT_REVISION,
    FULL_WORKSPACE_CORE_TOOL_HANDLES,
    FULL_WORKSPACE_REQUIRED_RESULT_BEHAVIORS,
    MAVERICK_AGENT_CANDIDATE_EXECUTION_FAMILY,
    inspect_full_workspace_contract,
    validate_full_workspace_contract_claim,
    validate_full_workspace_live_authority,
)
from core.runtime.hosted_harness_recipes import GOOGLE_GOVERNED_WORKSPACE_RECIPE
from core.runtime.hosted_tool_result_admission import (
    build_hosted_tool_result_preflight_resolver,
)
from core.runtime.tool_catalog import RuntimeToolCatalogBuilder
from core.runtime.tool_orchestrator import RuntimeToolOrchestrator
from core.runtime.tool_schema import provider_tool_name
from tests.unit.runtime_tools.test_tool_orchestrator import (
    _RuntimeToolOrchestratorFixture,
)
from core.runtime.hosted_tool_result_behavior import (
    inspect_hosted_tool_result_behavior,
)
from core.runtime.hosted_shell_process_behavior import (
    HOSTED_SHELL_PROCESS_BEHAVIOR_IDS,
    inspect_hosted_shell_process_behavior,
)


class FullWorkspaceResultContractTest(unittest.TestCase):
    def setUp(self) -> None:
        self.capabilities = SimpleNamespace(
            streaming=True,
            tool_orchestration=True,
            cli=True,
            mcp=True,
            skill_catalog=True,
            filesystem_list=True,
            filesystem_read=True,
            filesystem_write=True,
            shell=True,
            interrupt=True,
            recovery=True,
            confirmation_resume=True,
            app_references=True,
            confirmations=True,
            attachment_modalities=("file",),
        )
        self.policy = SimpleNamespace(
            require_confirmation_for_mutating=True,
            require_confirmation_for_destructive=True,
            allowed_surface_kinds=(
                "cli",
                "mcp",
                "app-interface",
                "core-capability",
            ),
            allowed_remote_data_classes=("public",),
            tool_handle_mode="all_currently_authorized",
            allowed_tool_handles=(),
        )

    def test_live_behavior_not_mode_strings_controls_completion(self) -> None:
        verified = inspect_hosted_tool_result_behavior()
        report = inspect_full_workspace_contract(
            capabilities=self.capabilities,
            policy=self.policy,
        )

        self.assertTrue(report.complete)
        self.assertEqual(report.missing_result_behaviors, ())
        self.assertEqual(
            tuple(verified),
            FULL_WORKSPACE_REQUIRED_RESULT_BEHAVIORS,
        )

    def test_result_gate_names_every_mutating_filesystem_workflow(self) -> None:
        self.assertTrue(
            {
                "core-capability:filesystem.write:create",
                "core-capability:filesystem.write:replace",
                "core-capability:filesystem.edit",
                "core-capability:filesystem.patch",
                "core-capability:filesystem.move",
                "core-capability:filesystem.delete",
                "core-capability:filesystem.read-after-write",
            }.issubset(FULL_WORKSPACE_REQUIRED_RESULT_BEHAVIORS)
        )

    def test_result_gate_executes_every_process_handler(self) -> None:
        inspect_hosted_shell_process_behavior.cache_clear()
        self.addCleanup(inspect_hosted_shell_process_behavior.cache_clear)
        self.assertEqual(
            inspect_hosted_shell_process_behavior(),
            HOSTED_SHELL_PROCESS_BEHAVIOR_IDS,
        )

        with patch(
            "core.runtime.hosted_shell_process_behavior.build_core_runtime_tool_capabilities",
            side_effect=RuntimeError("broken process adapter"),
        ):
            inspect_hosted_shell_process_behavior.cache_clear()
            self.assertEqual(inspect_hosted_shell_process_behavior(), ())

    def test_result_gate_executes_revocation_and_marker_negative_probes(self) -> None:
        self.assertTrue(
            {
                "security:filesystem.marker-narrowing",
                "security:filesystem.revoke-rebuild",
                "security:tool-result.revoke-egress",
            }.issubset(FULL_WORKSPACE_REQUIRED_RESULT_BEHAVIORS)
        )

    def test_maverick_agent_family_requires_an_atomic_full_contract(self) -> None:
        incomplete = SimpleNamespace(
            full_workspace_contract_revision="",
            execution_family="maverick_agent",
        )
        candidate = SimpleNamespace(
            full_workspace_contract_revision="",
            execution_family=MAVERICK_AGENT_CANDIDATE_EXECUTION_FAMILY,
        )

        with self.assertRaisesRegex(
            CapabilityCertificateError,
            "full_workspace_execution_family_contract_required",
        ):
            validate_full_workspace_contract_claim(
                profile=incomplete,
                certificate=incomplete,
            )
        validate_full_workspace_contract_claim(
            profile=candidate,
            certificate=candidate,
        )
        claimed_candidate = SimpleNamespace(
            full_workspace_contract_revision=FULL_WORKSPACE_CONTRACT_REVISION,
            execution_family=MAVERICK_AGENT_CANDIDATE_EXECUTION_FAMILY,
        )
        with self.assertRaisesRegex(
            CapabilityCertificateError,
            "full_workspace_candidate_contract_forbidden",
        ):
            validate_full_workspace_contract_claim(
                profile=claimed_candidate,
                certificate=claimed_candidate,
            )
        with self.assertRaisesRegex(
            CapabilityCertificateError,
            "full_workspace_execution_family_mismatch",
        ):
            validate_full_workspace_contract_claim(
                profile=candidate,
                certificate=incomplete,
            )

    def test_complete_requires_every_behavior_probe(self) -> None:
        report = inspect_full_workspace_contract(
            capabilities=self.capabilities,
            policy=self.policy,
        )
        self.assertTrue(report.complete)

        with patch(
            "core.runtime.full_workspace_contract._hosted_tool_result_behaviors",
            return_value=FULL_WORKSPACE_REQUIRED_RESULT_BEHAVIORS[:-1],
        ):
            incomplete = inspect_full_workspace_contract(
                capabilities=self.capabilities,
                policy=self.policy,
            )

        self.assertFalse(incomplete.complete)
        self.assertEqual(
            incomplete.missing_result_behaviors,
            (FULL_WORKSPACE_REQUIRED_RESULT_BEHAVIORS[-1],),
        )

    def test_claim_requires_complete_behavior_and_exact_surface(self) -> None:
        capabilities = RuntimeCapabilitySet(
            streaming=True,
            tool_orchestration=True,
            cli=True,
            mcp=True,
            skill_catalog=True,
            filesystem_list=True,
            filesystem_read=True,
            filesystem_write=True,
            shell=True,
            interrupt=True,
            same_turn_steering=False,
            recovery=True,
            confirmation_resume=True,
            provider_private_state=True,
            attachment_modalities=("file",),
            app_references=True,
            confirmations=True,
        )
        policy = replace(
            codex_runtime_policy(),
            tool_handle_mode="exact",
            allowed_tool_handles=FULL_WORKSPACE_CORE_TOOL_HANDLES,
            require_confirmation_for_mutating=True,
            require_confirmation_for_destructive=True,
            allowed_remote_data_classes=("public",),
        )
        recipe = GOOGLE_GOVERNED_WORKSPACE_RECIPE
        profile = SimpleNamespace(
            full_workspace_contract_revision=FULL_WORKSPACE_CONTRACT_REVISION,
            policy_ceiling=policy,
            execution_family="maverick_agent",
            harness_recipe_id=recipe.recipe_id,
            harness_recipe_revision=recipe.revision,
            harness_recipe_digest=recipe.recipe_digest,
            provider_capability_catalog_digest=recipe.capability_catalog_digest,
            semantic_projection_compiler_revision=(
                recipe.semantic_projection_compiler_revision
            ),
            tool_contract_revision=FULL_WORKSPACE_CONTRACT_REVISION,
            context_policy=recipe.context_policy,
        )
        certificate = SimpleNamespace(
            full_workspace_contract_revision=FULL_WORKSPACE_CONTRACT_REVISION,
            execution_family="maverick_agent",
            certified_capabilities=capabilities,
        )

        self.assertTrue(
            inspect_full_workspace_contract(
                capabilities=capabilities,
                policy=policy,
            ).complete
        )
        validate_full_workspace_contract_claim(
            profile=profile,
            certificate=certificate,
        )
        with self.assertRaisesRegex(
            CapabilityCertificateError,
            "full_workspace_contract_live_authority_incomplete",
        ):
            validate_full_workspace_live_authority(
                revision=FULL_WORKSPACE_CONTRACT_REVISION,
                capabilities=capabilities,
                policy=policy,
                allowed_handles=FULL_WORKSPACE_CORE_TOOL_HANDLES[:-1],
            )
        self.assertFalse(
            inspect_full_workspace_contract(
                capabilities=capabilities,
                policy=replace(
                    policy,
                    require_confirmation_for_destructive=False,
                ),
            ).complete
        )
        for surface in ("cli", "mcp", "app-interface", "core-capability"):
            with self.subTest(surface=surface):
                narrowed = replace(
                    policy,
                    allowed_surface_kinds=tuple(
                        item
                        for item in policy.allowed_surface_kinds
                        if item != surface
                    ),
                )
                self.assertFalse(
                    inspect_full_workspace_contract(
                        capabilities=capabilities,
                        policy=narrowed,
                    ).complete
                )
        for missing in ("cli", "filesystem_write", "confirmations"):
            with self.subTest(missing=missing), self.assertRaisesRegex(
                CapabilityCertificateError,
                "full_workspace_contract_incomplete",
            ):
                validate_full_workspace_contract_claim(
                    profile=profile,
                    certificate=SimpleNamespace(
                        full_workspace_contract_revision=(
                            FULL_WORKSPACE_CONTRACT_REVISION
                        ),
                        execution_family="maverick_agent",
                        certified_capabilities=replace(
                            capabilities,
                            **{missing: False},
                        ),
                    ),
                )


class HostedResultPreflightExecutionTest(
    _RuntimeToolOrchestratorFixture,
    unittest.TestCase,
):
    def test_mutating_handler_is_denied_before_effect(self) -> None:
        orchestrator = RuntimeToolOrchestrator(
            catalog_builder=RuntimeToolCatalogBuilder(
                cli_registry=self.cli_registry,
                mcp_registry=self.mcp_registry,
                result_preflight_resolver=(
                    build_hosted_tool_result_preflight_resolver(
                        cli_registry=self.cli_registry,
                        mcp_registry=self.mcp_registry,
                    )
                ),
            ),
            ledger=self.ledger,
        )
        authority = replace(
            self.authority,
            allowed_remote_data_classes=("public",),
        )

        outcome = orchestrator.invoke_provider_tool(
            provider_tool_name=provider_tool_name("mcp:fixture_mutate"),
            provider_tool_call_id="call-preflight-mutating",
            arguments={"value": 1},
            authority=authority,
            context=self.context,
            turn_id="turn-tools",
            policy=self.policy,
        )

        self.assertEqual(outcome.invocation.state, "denied")
        self.assertEqual(
            outcome.invocation.failure_reason,
            "tool_result_egress_not_guaranteed",
        )
        self.assertEqual(self.mcp_calls, 0)


if __name__ == "__main__":
    unittest.main()
