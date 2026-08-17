from __future__ import annotations

from datetime import UTC, datetime
import json
from types import SimpleNamespace
import unittest

from core.api.runtime_tool_confirmation_api import handle_runtime_tool_confirmation
from core.api.session_api import RequestSession
from core.runtime.runtime_session import RuntimeSessionRecord
from core.runtime.runtime_state import RuntimeStateRecord
from core.runtime.runtime_turns import RuntimeTurnRecord
from core.runtime.store import RuntimeCollections, RuntimeDocumentStore
from core.runtime.tool_ledger import RuntimeToolLedger
from core.runtime.tool_private_payloads import InMemoryRuntimeToolPrivatePayloadStore
from tests.support.collections import FakeCollection


NOW = datetime(2026, 8, 16, tzinfo=UTC)


class RuntimeToolConfirmationApiTest(unittest.TestCase):
    def setUp(self) -> None:
        self.store = RuntimeDocumentStore(
            RuntimeCollections(
                sessions=FakeCollection(),
                turns=FakeCollection(),
                events=FakeCollection(),
                processes=FakeCollection(),
                states=FakeCollection(),
                threads=FakeCollection(),
                tool_invocations=FakeCollection(),
                tool_confirmation_grants=FakeCollection(),
            )
        )
        self.ledger = RuntimeToolLedger(
            store=self.store,
            private_payload_store=InMemoryRuntimeToolPrivatePayloadStore(),
            digest_key=b"runtime-tool-api-test-key-material",
        )
        self.store.save_session(
            RuntimeSessionRecord(
                session_id="session-confirm",
                workspace_id="default",
                agent_id="chat",
                status="running",
                requested_mode="sandbox",
                effective_mode="sandbox",
                workspace_root="/workspace",
                workdir="/workspace",
                runtime_root="/runtime",
                started_at=NOW,
                updated_at=NOW,
                ended_at=None,
                last_progress_at=NOW,
                owner_user_id="user-1",
            )
        )
        self.store.save_turn(
            RuntimeTurnRecord(
                turn_id="turn-confirm",
                session_id="session-confirm",
                workspace_id="default",
                status="waiting_for_tool_confirmation",
                input_text="change it",
                created_at=NOW,
                updated_at=NOW,
                started_at=NOW,
                completed_at=None,
                failure_reason=None,
            )
        )
        self.store.save_state(
            RuntimeStateRecord(
                session_id="session-confirm",
                workspace_id="default",
                current_turn_id="turn-confirm",
                session_status="running",
                turn_status="waiting_for_tool_confirmation",
                last_progress_at=NOW,
                watchdog_deadline_at=NOW.replace(second=45),
                forced_stop_reason=None,
                last_error_detail=None,
                updated_at=NOW,
            )
        )
        proposed, _ = self.ledger.propose(
            workspace_id="default",
            session_id="session-confirm",
            turn_id="turn-confirm",
            provider_tool_call_id="provider-call-1",
            tool_handle="mcp:fixture_mutate",
            arguments={"secret_value": "never expose"},
            effect_class="mutating",
            policy_revision="policy:1",
            authority_digest="authority:1",
            now=NOW,
        )
        validating = self.ledger.transition(proposed, "validating", now=NOW)
        validated = self.ledger.transition(validating, "validated", now=NOW)
        self.pending = self.ledger.transition(validated, "awaiting_confirmation", now=NOW)
        workspace_store = SimpleNamespace(
            get_workspace=lambda _workspace_id: SimpleNamespace(status="active"),
            get_membership=lambda **_kwargs: SimpleNamespace(status="active", role="member"),
        )
        self.state = SimpleNamespace(
            runtime_store=self.store,
            runtime_tool_ledger=self.ledger,
            workspace_store=workspace_store,
            runtime_event_bus=None,
        )
        self.context = RequestSession(
            user=SimpleNamespace(user_id="user-1", platform_role="member"),
            session=SimpleNamespace(session_id="auth-1"),
            workspace_id="default",
        )

    def test_approval_is_authenticated_persisted_and_redaction_safe(self) -> None:
        status, payload = self._invoke(
            method="POST",
            body={
                "decision": "approve",
                "arguments_digest": self.pending.arguments_digest,
                "expected_invocation_revision": self.pending.revision,
            },
        )

        self.assertEqual(status, "200 OK")
        self.assertEqual(payload["invocation"]["state"], "awaiting_confirmation")
        self.assertEqual(payload["confirmation"]["state"], "active")
        self.assertEqual(payload["turn_status"], "active")
        serialized = json.dumps(payload)
        self.assertNotIn("never expose", serialized)
        self.assertNotIn("private_ref", serialized)
        self.assertNotIn("idempotency", serialized)
        self.assertNotIn("grant_id", serialized)

        replay_status, replay = self._invoke(
            method="POST",
            body={
                "decision": "approve",
                "arguments_digest": self.pending.arguments_digest,
                "expected_invocation_revision": self.pending.revision,
            },
        )
        self.assertEqual(replay_status, "200 OK")
        self.assertEqual(replay["confirmation"]["state"], "active")
        self.assertEqual(len(self.store.list_tool_confirmation_grants(invocation_id=self.pending.invocation_id)), 1)
        confirmation_events = [
            item
            for item in self.store.list_events("session-confirm")
            if item.event_type == "runtime.tool_call.confirmation_approved"
        ]
        self.assertEqual(len(confirmation_events), 1)

    def test_digest_mismatch_fails_closed(self) -> None:
        status, payload = self._invoke(
            method="POST",
            body={
                "decision": "approve",
                "arguments_digest": "0" * 64,
                "expected_invocation_revision": self.pending.revision,
            },
        )
        self.assertEqual(status, "409 Conflict")
        self.assertEqual(payload["error"], "tool_confirmation_digest_mismatch")
        self.assertEqual(self.store.get_turn("turn-confirm").status, "waiting_for_tool_confirmation")

    def test_read_exposes_the_pinned_turn_confirmation_deadline(self) -> None:
        status, payload = self._invoke(method="GET", body={})

        self.assertEqual(status, "200 OK")
        self.assertEqual(
            payload["confirmation_deadline_at"],
            "2026-08-16T00:00:45+00:00",
        )

    def _invoke(self, *, method: str, body: dict) -> tuple[str, dict]:
        statuses: list[str] = []
        response = handle_runtime_tool_confirmation(
            self.state,
            self.context,
            turn_id="turn-confirm",
            invocation_id=self.pending.invocation_id,
            method=method,
            body=body,
            start_response=lambda status, _headers: statuses.append(status),
        )
        return statuses[0], json.loads(b"".join(response).decode("utf-8"))


if __name__ == "__main__":
    unittest.main()
