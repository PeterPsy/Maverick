"""Positive enable/create/queue/dispatch plumbing without substituting guards."""

from dataclasses import replace
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from core.providers.errors import AgenticProfileError
from core.runtime.errors import RuntimeTurnQueueRejectedError
from core.runtime.hosted_agentic_models import HostedAgenticLoopError
from core.runtime.hosted_runtime_registry_builder import build_hosted_provider_runtime_registry
from core.runtime.lifecycle_service import create_runtime_session, create_child_runtime_session, queue_runtime_turn
from core.runtime.provider_start_handoff import runtime_provider_start_handoff
from core.runtime.remote_agentic_admission import require_remote_agentic_session_admission
from core.runtime.turn_queue_admission import require_turn_queue_session_executable
from core.workspaces.data_governance import revoke_data_attestation
from tests.support.remote_admission_path import admitted_fixture


class RemoteAdmissionPathTest(unittest.TestCase):
    def setUp(self):
        self.state, self.binding, self.attestation = admitted_fixture(self)

    def create(self):
        session = create_runtime_session(
            self.state.runtime_store, session_id=self.binding.session_id, workspace_id="default", agent_id="chat",
            owner_user_id="offline-actor", requested_mode="sandbox", execution_binding=self.binding,
            workspace_store=self.state.workspace_store, start_path=self.state.repository_root,
        )
        self.assertEqual(session.preparation_status, "prepared")
        return session

    def revoke(self):
        revoked = revoke_data_attestation(self.attestation, actor_id="offline-operator", expected_revision=1,
                                         reason="fixture retired")
        self.state.workspace_store.save_data_attestation(revoked, expected_revision=1)

    def test_enable_create_queue_and_real_dispatch_resolution(self):
        session = self.create()
        turn = queue_runtime_turn(self.state.runtime_store, session_id=session.session_id, turn_id="queued",
                                  workspace_store=self.state.workspace_store)
        self.assertEqual(turn.status, "queued")
        with runtime_provider_start_handoff(self.state.runtime_store, session_id=session.session_id,
                                           workspace_store=self.state.workspace_store) as (fresh, _accepted):
            runtime = build_hosted_provider_runtime_registry(workspace_store=self.state.workspace_store).resolve(fresh.execution_binding)
            self.assertEqual(runtime.model_provider_id, "openrouter")
        child = create_child_runtime_session(self.state.runtime_store, parent_session_id=session.session_id,
                                             child_session_id="child", child_agent_id="child",
                                             workspace_store=self.state.workspace_store)
        self.assertEqual(child.execution_binding.workspace_id, "default")

    def test_revocation_after_queue_blocks_dispatch_and_a_fresh_registry(self):
        session = self.create()
        queue_runtime_turn(self.state.runtime_store, session_id=session.session_id, turn_id="queued",
                           workspace_store=self.state.workspace_store)
        self.revoke()
        transport = Mock()
        with self.assertRaises(RuntimeTurnQueueRejectedError):
            with runtime_provider_start_handoff(self.state.runtime_store, session_id=session.session_id,
                                               workspace_store=self.state.workspace_store):
                transport()
        # Reconstruct dependencies as a restarted worker would; no cached acceptance.
        from core.workspaces.store import WorkspaceDocumentStore
        restarted_store = WorkspaceDocumentStore(self.state.control_plane_collections.workspace)
        registry = build_hosted_provider_runtime_registry(workspace_store=restarted_store)
        with self.assertRaisesRegex(HostedAgenticLoopError, "attestation_revoked"):
            registry.resolve(self.binding)
        with self.assertRaisesRegex(AgenticProfileError, "attestation_revoked"):
            create_child_runtime_session(self.state.runtime_store, parent_session_id=session.session_id,
                                         child_session_id="denied", child_agent_id="child",
                                         workspace_store=self.state.workspace_store)
        transport.assert_not_called()

    def test_snapshot_cannot_override_revocation_and_store_failure(self):
        self.revoke()
        with self.assertRaisesRegex(AgenticProfileError, "attestation_revoked"):
            require_remote_agentic_session_admission(self.binding, workspace_id="default",
                workspace_store=self.state.workspace_store, workspace_attestation=self.attestation)
        with patch.object(self.state.workspace_store, "get_data_attestation", side_effect=OSError), self.assertRaisesRegex(
            AgenticProfileError, "attestation_required",
        ):
            require_remote_agentic_session_admission(self.binding, workspace_id="default",
                workspace_store=self.state.workspace_store, workspace_attestation=self.attestation)

    def test_changed_workspace_owner_or_tuple_cannot_use_stale_queue_input(self):
        session = self.create()
        for changes in ({"workspace_id": "another"}, {"owner_user_id": "another"},
                        {"execution_binding": replace(self.binding, model_id="another")}):
            with self.subTest(changes=tuple(changes)), self.assertRaises(RuntimeTurnQueueRejectedError):
                require_turn_queue_session_executable(self.state.runtime_store, replace(session, **changes),
                                                      workspace_store=self.state.workspace_store)

    def test_production_remains_closed_even_for_valid_attestation(self):
        with patch("core.runtime.remote_agentic_admission.REMOTE_AGENTIC_ATTESTATION_AVAILABLE", False), self.assertRaisesRegex(
            AgenticProfileError, "attestation_unavailable",
        ):
            self.create()

    def test_persisted_identity_changes_fence_both_hosted_transport_refreshes(self):
        session = self.create()
        loop = self.state.provider_registry.get_agentic_runtime_adapter("maverick-tool-loop").loop
        context = SimpleNamespace(session=session, binding=session.execution_binding, correlation_id="turn")
        for updates in ({"owner_user_id": "another"}, {"agent_type_id": "another"},
                        {"effective_mode": "full-access"}):
            # Change authoritative storage after the loop received its snapshot.
            self.state.runtime_store.save_session(replace(session, **updates))
            for refresh in (lambda: loop.authority_refresher(context),
                            lambda: loop.authority_revalidator(context, object())):
                with self.assertRaisesRegex(HostedAgenticLoopError, "session_identity_changed"):
                    refresh()
            self.state.runtime_store.save_session(session)
        context.binding = replace(self.binding, model_id="another")
        with self.assertRaisesRegex(HostedAgenticLoopError, "session_identity_changed"):
            loop.authority_refresher(context)


if __name__ == "__main__":
    unittest.main()
