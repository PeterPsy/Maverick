"""Positive enable/create/queue/dispatch plumbing without substituting guards."""

from dataclasses import replace
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from core.api.runtime_api import _create_session, _preflight_runtime_session_creation_before_persistence
from core.api.settings_api import _runtime_session_settings_payload
from core.providers.errors import AgenticProfileError
from core.providers.service import resolve_workspace_provider_status
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

    def api_preflight(self):
        context = SimpleNamespace(user=self.state.identity_store.list_users()[0], workspace_id="default")
        # Full Workspace currently requires full-access execution policy; do not
        # stub the API's capability preflight or silently remove its shell gate.
        body = {"runtime_mode": "agentic", "requested_mode": "full-access",
                "workspace_profile_binding_id": self.binding.workspace_binding_id}
        preflight = _preflight_runtime_session_creation_before_persistence(self.state, context, body)
        return context, body, preflight

    def test_complete_api_preflight_create_queue_and_dispatch_resolution(self):
        context, body, preflight = self.api_preflight()
        session = _create_session(self.state, context, body, agent_id="chat",
                                  start_path=self.state.repository_root, preflight=preflight)
        self.assertEqual(session.status, "running")
        self.assertEqual(session.owner_user_id, context.user.user_id)
        turn = queue_runtime_turn(self.state.runtime_store, session_id=session.session_id, turn_id="api-queued",
                                  workspace_store=self.state.workspace_store)
        self.assertEqual(turn.status, "queued")
        with runtime_provider_start_handoff(self.state.runtime_store, session_id=session.session_id,
                                           workspace_store=self.state.workspace_store) as (fresh, _accepted):
            runtime = build_hosted_provider_runtime_registry(workspace_store=self.state.workspace_store).resolve(fresh.execution_binding)
            self.assertEqual(runtime.model_provider_id, "openrouter")

    def test_settings_inventory_rechecks_the_same_live_attestation(self):
        session = self.create()
        self.assertEqual(_runtime_session_settings_payload(self.state, session)["agentic_containment"]["status"], "GO")
        self.revoke()
        self.assertEqual(_runtime_session_settings_payload(self.state, session)["agentic_containment"]["reason_code"],
                         "remote_agentic_attestation_revoked")

    def test_default_provider_status_receives_the_authoritative_workspace_store(self):
        state, _binding, attestation = admitted_fixture(self, is_default=True)
        def status():
            return resolve_workspace_provider_status(state.provider_store, workspace_id="default",
                registry=state.provider_registry, workspace_store=state.workspace_store)
        self.assertTrue(status().configured)
        state.workspace_store.save_data_attestation(
            revoke_data_attestation(attestation, actor_id="offline-operator", expected_revision=1, reason="retired"),
            expected_revision=1,
        )
        self.assertEqual(status().blocked_detail, "remote_agentic_attestation_revoked")

    def test_revocation_between_api_preflight_and_create_never_persists(self):
        context, body, preflight = self.api_preflight()
        before = self.state.runtime_store.list_all_sessions()
        self.revoke()
        with patch.object(self.state.runtime_store, "insert_session",
                          wraps=self.state.runtime_store.insert_session) as insert:
            with self.assertRaisesRegex(AgenticProfileError, "attestation_revoked"):
                _create_session(self.state, context, body, agent_id="chat",
                                start_path=self.state.repository_root, preflight=preflight)
        insert.assert_not_called()
        self.assertEqual(self.state.runtime_store.list_all_sessions(), before)

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

    def test_fresh_process_reads_revocation_from_disk_before_dispatch(self):
        session = self.create()
        queue_runtime_turn(self.state.runtime_store, session_id=session.session_id, turn_id="restart-queued",
                           workspace_store=self.state.workspace_store)
        self.revoke()
        code = """
from pathlib import Path
import sys
from unittest.mock import patch
from core.api.control_store import ControlStoreSettings, build_control_plane_collections
from core.runtime.hosted_agentic_models import HostedAgenticLoopError
from core.runtime.hosted_runtime_registry_builder import build_hosted_provider_runtime_registry
from core.runtime.runtime_session import runtime_session_from_document
from core.runtime.session_collection import RuntimeSessionJsonCollection
from core.workspaces.store import WorkspaceDocumentStore

collections = build_control_plane_collections(ControlStoreSettings('json', Path(sys.argv[1])))
workspaces = WorkspaceDocumentStore(collections.workspace)
documents = RuntimeSessionJsonCollection(start_path=Path(sys.argv[2]), filename='session.json')
session = runtime_session_from_document(documents.find_one({'session_id': sys.argv[3]}))
# Offline future-release condition only; no admission guard is replaced.
with patch('core.runtime.remote_agentic_admission.REMOTE_AGENTIC_ATTESTATION_AVAILABLE', True):
    try:
        build_hosted_provider_runtime_registry(workspace_store=workspaces).resolve(session.execution_binding)
    except HostedAgenticLoopError as error:
        print(error.reason_code)
    else:
        raise SystemExit('revoked workspace admitted after restart')
"""
        child = subprocess.run(
            [sys.executable, "-c", code, str(self.state.control_store_settings.json_root),
             str(self.state.repository_root), session.session_id],
            cwd=Path(__file__).resolve().parents[3], capture_output=True, text=True, timeout=30, check=False,
        )
        self.assertEqual(child.returncode, 0, child.stderr)
        self.assertEqual(child.stdout.strip(), "remote_agentic_attestation_revoked")
        self.assertEqual(len(self.state.runtime_store.list_turns(session.session_id)), 1)

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
        with patch.dict("os.environ", {"MAVERICK_CERTIFICATION_ALLOW_LIVE": "1"}), patch(
            "core.runtime.remote_agentic_admission.REMOTE_AGENTIC_ATTESTATION_AVAILABLE", False,
        ), self.assertRaisesRegex(
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
