"""Regression contract for the direct agentic runtime configuration model."""

from __future__ import annotations

from dataclasses import fields
from pathlib import Path
import unittest

from core.providers.agentic_models import (
    AgenticProfileDefinition,
    WorkspaceAgenticProfileBinding,
)
from core.runtime.execution_binding import RuntimeExecutionBinding


ROOT = Path(__file__).resolve().parents[3]


class AgenticRuntimeSimplicityContractTest(unittest.TestCase):
    def test_control_plane_records_have_no_release_lifecycle(self) -> None:
        self.assertFalse(
            {"revision", "execution_family"}
            & {item.name for item in fields(AgenticProfileDefinition)}
        )
        self.assertFalse(
            {"definition_revision", "revision", "lineage_binding_ids"}
            & {item.name for item in fields(WorkspaceAgenticProfileBinding)}
        )

    def test_session_binding_contains_only_execution_inputs(self) -> None:
        self.assertEqual(
            {item.name for item in fields(RuntimeExecutionBinding)},
            {
                "execution_binding_id",
                "session_id",
                "workspace_id",
                "workspace_binding_id",
                "runtime_engine_id",
                "adapter_id",
                "adapter_version",
                "model_provider_id",
                "model_id",
                "provider_protocol",
                "provider_api_version",
                "routing_constraint_snapshot",
                "credential_binding_id",
                "reasoning_effort",
                "capabilities_snapshot",
                "execution_mode",
                "runtime_policy_snapshot",
                "egress_policy_id",
                "egress_policy_revision",
                "created_at",
                "context_policy_snapshot",
                "model_revision",
                "model_revision_policy",
            },
        )

    def test_removed_lifecycle_modules_do_not_return(self) -> None:
        for relative in (
            "core/providers/agentic_migration.py",
            "core/providers/agentic_default_migration.py",
            "core/providers/agentic_lineage_admission.py",
            "core/providers/execution_family_migration.py",
            "core/providers/runtime_adapter_identity.py",
            "core/runtime/full_workspace_contract.py",
            "core/runtime/continuation_handoff.py",
            "core/runtime/continuation_lineage.py",
            "core/recovery/continuation_admission.py",
            "core/recovery/continuation_fork.py",
            "core/recovery/continuation_snapshot.py",
            "core/recovery/continuation_provider_snapshot.py",
        ):
            self.assertFalse((ROOT / relative).exists(), relative)

    def test_old_certificate_and_digest_schema_is_absent(self) -> None:
        fragments = ("providers", "runtime")
        source = "\n".join(
            path.read_text(encoding="utf-8")
            for fragment in fragments
            for path in (ROOT / "core" / fragment).glob("*.py")
        )
        for forbidden in (
            "capability_" + "certificate",
            "certificate_" + "evidence",
            "certified_" + "capabilities",
            "certified_" + "reasoning_efforts",
            "native_connection_" + "certificate",
            "tool_authority_ceiling_" + "digest",
            "adapter_identity_" + "digest",
            "provider_capability_catalog_" + "digest",
            "certificate_" + "expires_at",
            "capability_" + "tcb",
            "legacy_" + "inferred",
        ):
            self.assertNotIn(forbidden, source)

    def test_platform_boot_does_not_run_agentic_schema_migrations(self) -> None:
        platform_state = (ROOT / "core/api/platform_state.py").read_text(
            encoding="utf-8"
        )
        self.assertNotIn("migrate_agentic_runtime_schema", platform_state)

if __name__ == "__main__":
    unittest.main()
