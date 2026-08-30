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
            allowed_surface_kinds=("core-capability",),
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

        self.assertFalse(report.complete)
        self.assertEqual(
            report.missing_result_behaviors,
            tuple(
                handle
                for handle in FULL_WORKSPACE_REQUIRED_RESULT_BEHAVIORS
                if handle not in verified
            ),
        )
        self.assertIn("core-capability:shell.run", report.missing_result_behaviors)
        self.assertIn("core-capability:cli.run", report.missing_result_behaviors)

    def test_complete_requires_every_behavior_probe(self) -> None:
        with patch(
            "core.runtime.full_workspace_contract._hosted_tool_result_behaviors",
            return_value=FULL_WORKSPACE_REQUIRED_RESULT_BEHAVIORS,
        ):
            report = inspect_full_workspace_contract(
                capabilities=self.capabilities,
                policy=self.policy,
            )

        self.assertTrue(report.complete)

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
            certified_capabilities=capabilities,
        )

        self.assertFalse(
            inspect_full_workspace_contract(
                capabilities=capabilities,
                policy=policy,
            ).complete
        )
        with self.assertRaisesRegex(
            CapabilityCertificateError,
            "full_workspace_contract_incomplete",
        ):
            validate_full_workspace_contract_claim(
                profile=profile,
                certificate=certificate,
            )

        with patch(
            "core.runtime.full_workspace_contract._hosted_tool_result_behaviors",
            return_value=FULL_WORKSPACE_REQUIRED_RESULT_BEHAVIORS,
        ):
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
