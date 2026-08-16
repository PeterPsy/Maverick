from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
import unittest

from core.runtime.errors import RuntimeProviderStateError
from core.runtime.session_collection import RuntimeSessionJsonCollection
from core.runtime.store import RuntimeCollections, RuntimeDocumentStore
from core.runtime.tool_ledger import RuntimeToolLedger
from core.runtime.private_payload_store import EncryptedRuntimePrivatePayloadStore
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
