from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
import time
import unittest
from unittest.mock import patch

from core.runtime.errors import RuntimeProviderStateError
from core.runtime.private_payload_store import EncryptedRuntimePrivatePayloadStore
from core.runtime.session_collection import RuntimeSessionJsonCollection
from core.runtime.store import RuntimeCollections, RuntimeDocumentStore
from core.runtime.tool_errors import RuntimeToolError
from core.runtime.tool_ledger import RuntimeToolLedger
from core.runtime.tool_models import ToolInvocationRecord
from core.runtime.tool_private_payloads import (
    EncryptedRuntimeToolPrivatePayloadStore,
    InMemoryRuntimeToolPrivatePayloadStore,
)
from tests.support.collections import FakeCollection
from tests.support.repo import make_temp_repo_root


NOW = datetime(2026, 8, 16, tzinfo=UTC)


class RuntimeToolStoreTest(unittest.TestCase):
    def setUp(self) -> None:
        self.root = make_temp_repo_root(self)
        self.store = self._store()
        self.ledger = RuntimeToolLedger(
            store=self.store,
            private_payload_store=InMemoryRuntimeToolPrivatePayloadStore(),
            digest_key=b"runtime-tool-store-test-key-value",
        )

    def _store(self) -> RuntimeDocumentStore:
        return RuntimeDocumentStore(
            RuntimeCollections(
                sessions=FakeCollection(),
                turns=FakeCollection(),
                events=FakeCollection(),
                processes=FakeCollection(),
                states=FakeCollection(),
                threads=FakeCollection(),
                tool_invocations=RuntimeSessionJsonCollection(
                    start_path=self.root, filename="tool_invocations.json"
                ),
                tool_confirmation_grants=RuntimeSessionJsonCollection(
                    start_path=self.root, filename="tool_confirmation_grants.json"
                ),
            )
        )

    def test_json_records_reload_with_cas_and_delete_with_session(self) -> None:
        proposed, _ = self.ledger.propose(
            workspace_id="default",
            session_id="session-persist",
            turn_id="turn-persist",
            provider_tool_call_id="call-persist",
            tool_handle="mcp:fixture_mutate",
            arguments={"value": 1},
            effect_class="mutating",
            policy_revision="policy:1",
            authority_digest="authority:1",
            now=NOW,
        )
        validating = self.ledger.transition(proposed, "validating", now=NOW)
        validated = self.ledger.transition(validating, "validated", now=NOW)
        pending = self.ledger.transition(validated, "awaiting_confirmation", now=NOW)
        confirmed, grant = self.ledger.confirm(
            invocation_id=pending.invocation_id,
            decision="approve",
            arguments_digest=pending.arguments_digest,
            expected_invocation_revision=pending.revision,
            confirming_actor_id="user-1",
            policy_revision="policy:1",
            now=NOW,
        )

        reloaded = self._store()
        self.assertEqual(reloaded.get_tool_invocation(pending.invocation_id), confirmed)
        self.assertEqual(reloaded.get_tool_confirmation_grant(grant.grant_id), grant)
        with self.assertRaisesRegex(RuntimeProviderStateError, "identity fields are immutable"):
            reloaded.update_tool_invocation(
                replace(
                    confirmed,
                    resolved_tool_handle="mcp:other",
                    revision=confirmed.revision + 1,
                    updated_at=NOW + timedelta(seconds=1),
                ),
                expected_revision=confirmed.revision,
            )

        deleted = reloaded.delete_session_records("session-persist")
        self.assertEqual(deleted["tool_invocations"], 1)
        self.assertEqual(deleted["tool_confirmation_grants"], 1)
        self.assertEqual(reloaded.list_tool_invocations(session_id="session-persist"), [])

    def test_terminal_success_requires_a_live_persisted_execution_lease(self) -> None:
        live = self._start_leased_invocation(
            "call-live",
            datetime.now(tz=UTC) + timedelta(minutes=1),
        )
        succeeded = self.ledger.transition(
            live,
            "succeeded",
            result_private_ref="tool-private:live-result",
            result_summary={"serialized_bytes": 2},
            require_active_execution_lease_id="lease-call-live",
            now=NOW,
        )
        self.assertEqual(succeeded.state, "succeeded")

        expired = self._start_leased_invocation(
            "call-expired",
            datetime.now(tz=UTC) - timedelta(seconds=1),
        )
        with self.assertRaisesRegex(
            RuntimeToolError,
            "agent_finalization_time_reserve_reached",
        ):
            self.ledger.transition(
                expired,
                "succeeded",
                result_private_ref="tool-private:expired-result",
                result_summary={"serialized_bytes": 2},
                require_active_execution_lease_id="lease-call-expired",
                now=NOW,
            )
        self.assertEqual(
            self.store.get_tool_invocation(expired.invocation_id).state,
            "executing",
        )

    def test_terminal_success_rechecks_lease_before_session_file_replace(self) -> None:
        executing = self._start_leased_invocation(
            "call-slow-cas",
            datetime.now(tz=UTC) + timedelta(seconds=0.02),
        )
        collection = self.store.collections.tool_invocations
        self.assertIsInstance(collection, RuntimeSessionJsonCollection)
        assert isinstance(collection, RuntimeSessionJsonCollection)
        original_write = collection._write_documents

        def delayed_write(*args, **kwargs):
            time.sleep(0.05)
            return original_write(*args, **kwargs)

        with patch.object(collection, "_write_documents", side_effect=delayed_write):
            with self.assertRaisesRegex(
                RuntimeToolError,
                "agent_finalization_time_reserve_reached",
            ):
                self.ledger.transition(
                    executing,
                    "succeeded",
                    result_private_ref="tool-private:slow-cas-result",
                    result_summary={"serialized_bytes": 2},
                    require_active_execution_lease_id="lease-call-slow-cas",
                    now=NOW,
                )

        self.assertEqual(
            self.store.get_tool_invocation(executing.invocation_id).state,
            "executing",
        )

    def _start_leased_invocation(
        self,
        call_id: str,
        expires_at: datetime,
    ) -> ToolInvocationRecord:
        proposed, _ = self.ledger.propose(
            workspace_id="default",
            session_id="session-lease",
            turn_id="turn-lease",
            provider_tool_call_id=call_id,
            tool_handle="mcp:fixture_read",
            arguments={"value": 1},
            effect_class="read",
            policy_revision="policy:1",
            authority_digest="authority:1",
            now=NOW,
        )
        validating = self.ledger.transition(proposed, "validating", now=NOW)
        validated = self.ledger.transition(validating, "validated", now=NOW)
        authorized = self.ledger.transition(validated, "authorized", now=NOW)
        return self.ledger.transition(
            authorized,
            "executing",
            execution_lease_id=f"lease-{call_id}",
            execution_lease_expires_at=expires_at,
            now=NOW,
        )

    def test_encrypted_arguments_survive_process_restart_without_plaintext_on_disk(self) -> None:
        key = bytes(reversed(range(32)))

        def private_store() -> EncryptedRuntimeToolPrivatePayloadStore:
            return EncryptedRuntimeToolPrivatePayloadStore(
                EncryptedRuntimePrivatePayloadStore(
                    repository_root=self.root,
                    key_loader=lambda: key,
                )
            )
        ledger = RuntimeToolLedger(
            store=self.store,
            private_payload_store=private_store(),
            digest_key=b"runtime-tool-store-test-key-value",
        )
        proposed, _ = ledger.propose(
            workspace_id="default",
            session_id="session-restart",
            turn_id="turn-restart",
            provider_tool_call_id="call-restart",
            tool_handle="mcp:fixture_read",
            arguments={"canary": "private-argument-never-public"},
            effect_class="read",
            policy_revision="policy:1",
            authority_digest="authority:1",
            now=NOW,
        )

        restarted = RuntimeToolLedger(
            store=self._store(),
            private_payload_store=private_store(),
            digest_key=b"runtime-tool-store-test-key-value",
        )

        self.assertEqual(
            restarted.load_arguments(proposed),
            {"canary": "private-argument-never-public"},
        )
        private_file = next(
            self.root.glob("workspaces/default/runtime/sessions/session-restart/private/**/*.json")
        )
        self.assertNotIn(b"private-argument-never-public", private_file.read_bytes())


if __name__ == "__main__":
    unittest.main()
