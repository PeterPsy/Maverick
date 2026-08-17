from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
import unittest

from core.providers.agentic_models import codex_routing_constraint, codex_runtime_policy
from core.runtime.execution_binding import build_runtime_execution_binding
from core.runtime.lifecycle_service_sessions import create_child_runtime_session
from core.runtime.runtime_session import RuntimeSessionGrantRecord, RuntimeSessionRecord
from core.runtime.session_provider_state import initialize_bound_provider_state
from core.runtime.store import RuntimeCollections, RuntimeDocumentStore
from tests.support.collections import FakeCollection
from tests.support.repo import make_temp_repo_root


NOW = datetime(2026, 8, 17, tzinfo=UTC)


class ChildExecutionBindingTest(unittest.TestCase):
    def test_child_forks_exact_ceiling_with_independent_state_and_no_parent_grant(self) -> None:
        root = make_temp_repo_root(self)
        runtime_root = root / "workspaces/default/runtime/sessions/root-session"
        runtime_root.mkdir(parents=True, exist_ok=True)
        store = RuntimeDocumentStore(
            RuntimeCollections(
                sessions=FakeCollection(),
                turns=FakeCollection(),
                events=FakeCollection(),
                processes=FakeCollection(),
                states=FakeCollection(),
                threads=FakeCollection(),
                provider_states=FakeCollection(),
            )
        )
        policy = codex_runtime_policy()
        parent_binding = build_runtime_execution_binding(
            session_id="root-session",
            workspace_id="default",
            profile_definition_id="profile-child-fixture",
            profile_definition_revision="1",
            workspace_binding_id="workspace-child-fixture",
            workspace_binding_revision=0,
            capability_certificate_id="certificate-child-fixture",
            certificate_evidence_digest="a" * 64,
            runtime_engine_id="fake-hosted-engine",
            adapter_id="fake-hosted-adapter",
            adapter_version="1",
            adapter_artifact_digest="b" * 64,
            model_provider_id="fake-model-provider",
            model_id="fake-model",
            provider_protocol="fake-stream-v1",
            provider_api_version="v1",
            routing_constraint=codex_routing_constraint(),
            credential_binding_id=None,
            reasoning_effort=None,
            execution_mode="sandbox",
            profile_policy_ceiling=policy,
            workspace_policy_ceiling=policy,
            egress_policy_id="fake-egress",
            egress_policy_revision="1",
            created_at=NOW,
        )
        parent = RuntimeSessionRecord(
            session_id="root-session",
            workspace_id="default",
            agent_id="chat",
            status="running",
            requested_mode=None,
            effective_mode="sandbox",
            workspace_root=str(root / "workspaces/default"),
            workdir=str(root / "workspaces/default"),
            runtime_root=str(runtime_root),
            started_at=NOW,
            updated_at=NOW,
            ended_at=None,
            last_progress_at=NOW,
            owner_user_id="parent-user",
            grants=[
                RuntimeSessionGrantRecord(
                    operation="interrupt",
                    grantee_kind="user",
                    grantee_id="parent-user",
                )
            ],
            execution_binding=parent_binding,
        )
        store.insert_session(parent)
        initialize_bound_provider_state(
            store,
            parent_binding,
            session_id=parent.session_id,
            workspace_id=parent.workspace_id,
            now=NOW,
        )

        child = create_child_runtime_session(
            store,
            parent_session_id=parent.session_id,
            child_session_id="child-session",
            child_agent_id="research-agent",
            system_prompt="Use only the supplied synthetic fixture.",
            skill_ids=["storage"],
            now=NOW,
        )

        self.assertIsNone(child.owner_user_id)
        self.assertEqual(child.grants, [])
        self.assertEqual(child.thread_visibility, "hidden")
        self.assertIsNotNone(child.execution_binding)
        child_binding = child.execution_binding
        assert child_binding is not None
        self.assertNotEqual(
            child_binding.execution_binding_id,
            parent_binding.execution_binding_id,
        )
        self.assertNotEqual(child_binding.binding_digest, parent_binding.binding_digest)
        self.assertEqual(
            replace(
                child_binding,
                execution_binding_id=parent_binding.execution_binding_id,
                session_id=parent_binding.session_id,
                binding_digest=parent_binding.binding_digest,
                created_at=parent_binding.created_at,
            ),
            parent_binding,
        )
        parent_state = store.get_provider_state(parent.session_id)
        child_state = store.get_provider_state(child.session_id)
        self.assertEqual(parent_state.session_id, parent.session_id)
        self.assertEqual(child_state.session_id, child.session_id)
        self.assertIsNone(child_state.provider_private_envelope)
        self.assertEqual(child_state.revision, 0)


if __name__ == "__main__":
    unittest.main()
