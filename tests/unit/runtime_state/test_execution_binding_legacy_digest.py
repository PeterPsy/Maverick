from __future__ import annotations

from dataclasses import asdict
from datetime import UTC, datetime
import unittest
from unittest.mock import patch

from core.providers.agentic_models import codex_routing_constraint, codex_runtime_policy
from core.runtime.execution_binding import (
    RuntimeExecutionBinding,
    build_runtime_execution_binding,
    canonical_digest,
    execution_binding_from_document,
)


class ExecutionBindingLegacyDigestTestCase(unittest.TestCase):
    def test_legacy_digest_validation_is_bounded_by_schema_groups(self) -> None:
        serialized = asdict(_execution_binding())
        for field_name in (
            "certified_reasoning_efforts",
            "default_reasoning_effort",
            "tcb_manifest_id",
            "tcb_manifest_version",
            "tcb_structure_digest",
            "tcb_live_digest",
        ):
            serialized.pop(field_name)
        for field_name in (
            "profile_policy_ceiling_snapshot",
            "workspace_policy_ceiling_snapshot",
        ):
            serialized[field_name].pop("allow_filesystem_list")
        serialized["tool_authority_ceiling_digest"] = canonical_digest(
            serialized["workspace_policy_ceiling_snapshot"]
        )
        serialized["binding_digest"] = canonical_digest(serialized)

        with patch(
            "core.runtime.execution_binding.canonical_digest",
            wraps=canonical_digest,
        ) as digest:
            rehydrated = execution_binding_from_document(serialized)

        self.assertEqual(rehydrated.binding_digest, serialized["binding_digest"])
        self.assertLessEqual(digest.call_count, 8)


def _execution_binding() -> RuntimeExecutionBinding:
    return build_runtime_execution_binding(
        session_id="session-legacy",
        workspace_id="default",
        profile_definition_id="profile-codex",
        profile_definition_revision="1",
        workspace_binding_id="workspace-codex",
        workspace_binding_revision=0,
        capability_certificate_id="certificate-codex",
        certificate_evidence_digest="a" * 64,
        runtime_engine_id="codex",
        adapter_id="codex-app-server",
        adapter_version="test",
        adapter_artifact_digest="b" * 64,
        model_provider_id="codex",
        model_id="gpt-test",
        provider_protocol="codex-app-server-stdio",
        provider_api_version=None,
        routing_constraint=codex_routing_constraint(),
        credential_binding_id=None,
        reasoning_effort=None,
        certified_reasoning_efforts=(),
        default_reasoning_effort=None,
        execution_mode="full-access",
        profile_policy_ceiling=codex_runtime_policy(),
        workspace_policy_ceiling=codex_runtime_policy(),
        egress_policy_id="egress-codex",
        egress_policy_revision="1",
        created_at=datetime(2026, 8, 27, tzinfo=UTC),
    )


if __name__ == "__main__":
    unittest.main()
