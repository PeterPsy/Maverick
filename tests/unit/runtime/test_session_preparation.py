from __future__ import annotations

from datetime import UTC, datetime
import unittest

from core.providers.agentic_models import codex_routing_constraint, codex_runtime_policy
from core.runtime.errors import RuntimeProviderStateError, RuntimeTransitionError
from core.runtime.execution_binding import build_runtime_execution_binding
from core.runtime.provider_start_handoff import RuntimeProviderStartHandoff
from core.runtime.service import create_runtime_session, transition_runtime_session
from core.runtime.store import RuntimeCollections, RuntimeDocumentStore
from tests.support.collections import FakeCollection
from tests.support.repo import make_temp_repo_root


NOW = datetime(2026, 8, 18, 12, 0, tzinfo=UTC)


class FailOnceStore:
    def __init__(self, store: RuntimeDocumentStore, method_name: str) -> None:
        self.store = store
        self.method_name = method_name
        self.failed = False

    def __getattr__(self, name: str):
        target = getattr(self.store, name)
        if name != self.method_name:
            return target

        def fail_once(*args, **kwargs):
            if not self.failed:
                self.failed = True
                raise RuntimeError(f"injected_{name}_failure")
            return target(*args, **kwargs)

        return fail_once


class RuntimeSessionPreparationTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.repo_root = make_temp_repo_root(self)
        self.store = RuntimeDocumentStore(
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
        self.binding = build_runtime_execution_binding(
            session_id="session-preparation",
            workspace_id="default",
            profile_definition_id="profile",
            profile_definition_revision="1",
            workspace_binding_id="workspace-binding",
            workspace_binding_revision=1,
            capability_certificate_id="certificate",
            certificate_evidence_digest="a" * 64,
            runtime_engine_id="fake-agentic",
            adapter_id="fake-adapter",
            adapter_version="1",
            adapter_artifact_digest="b" * 64,
            model_provider_id="fake-provider",
            model_id="fake-model",
            provider_protocol="fake-v1",
            provider_api_version="v1",
            routing_constraint=codex_routing_constraint(),
            credential_binding_id=None,
            reasoning_effort=None,
            execution_mode="sandbox",
            profile_policy_ceiling=codex_runtime_policy(),
            workspace_policy_ceiling=codex_runtime_policy(),
            egress_policy_id="fake-only",
            egress_policy_revision="1",
            created_at=NOW,
        )

    def _create(self, store=None):
        return create_runtime_session(
            store or self.store,
            session_id=self.binding.session_id,
            workspace_id=self.binding.workspace_id,
            agent_id="chat",
            execution_binding=self.binding,
            now=NOW,
            start_path=self.repo_root,
        )

    def test_retry_repairs_every_persistence_boundary_before_publication(self) -> None:
        for method_name in ("initialize_provider_state", "save_state", "mark_session_prepared"):
            with self.subTest(method_name=method_name):
                self.setUp()
                faulting = FailOnceStore(self.store, method_name)
                with self.assertRaisesRegex(RuntimeError, f"injected_{method_name}_failure"):
                    self._create(faulting)

                partial = self.store.get_session(self.binding.session_id)
                self.assertEqual(partial.preparation_status, "unprepared")
                with self.assertRaisesRegex(RuntimeTransitionError, "unprepared"):
                    transition_runtime_session(
                        self.store,
                        session_id=partial.session_id,
                        target_status="running",
                        now=NOW,
                    )
                with self.assertRaisesRegex(RuntimeTransitionError, "unprepared"):
                    with RuntimeProviderStartHandoff(self.store, session_id=partial.session_id):
                        pass

                repaired = self._create(faulting)
                self.assertEqual(repaired.preparation_status, "prepared")
                self.assertEqual(self.store.get_state(repaired.session_id).session_status, "created")
                provider_state = self.store.get_provider_state(repaired.session_id)
                self.assertEqual(provider_state.runtime_engine_id, self.binding.runtime_engine_id)

    def test_retry_with_different_aggregate_is_rejected(self) -> None:
        faulting = FailOnceStore(self.store, "save_state")
        with self.assertRaisesRegex(RuntimeError, "injected_save_state_failure"):
            self._create(faulting)

        with self.assertRaisesRegex(RuntimeProviderStateError, "execution binding is immutable"):
            create_runtime_session(
                self.store,
                session_id=self.binding.session_id,
                workspace_id=self.binding.workspace_id,
                agent_id="different-agent",
                execution_binding=self.binding,
                now=NOW,
                start_path=self.repo_root,
            )


if __name__ == "__main__":
    unittest.main()
