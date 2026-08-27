"""Persisted provider-step gates at every ordinary admission boundary."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
import unittest
from unittest.mock import Mock, patch

from core.providers.agentic_adapter import RuntimePrepareContext, RuntimeRecoveryContext
from core.recovery.continuation_admission import assess_runtime_session_admission
from core.runtime.errors import RuntimeTurnQueueRejectedError
from core.runtime.lifecycle_service_children import queue_runtime_turn
from core.runtime.workspace_api_token import (
    issue_workspace_api_token,
    register_workspace_api_token,
    validate_workspace_api_token_lifecycle,
)
from tests.support.fake_agentic_provider import DeterministicFakeAgenticClient
from tests.support.hosted_agentic_harness import HostedAgenticHarness
from tests.unit.runtime_state import test_hosted_agentic_recovery as recovery_tests


NOW = datetime(2026, 8, 27, tzinfo=UTC)


class HostedAgenticPersistedAdmissionTest(unittest.TestCase):
    _begin = recovery_tests.HostedAgenticRecoveryTest._begin
    _tool_step = recovery_tests.HostedAgenticRecoveryTest._tool_step

    def _ready_pairing(self):
        harness = HostedAgenticHarness(self)
        adapter = harness.adapter(DeterministicFakeAgenticClient())
        record, _outcome, _envelope = self._tool_step(
            harness,
            adapter,
            request_id="request-admission-source",
        )
        recovered = asyncio.run(
            adapter.recover(
                RuntimeRecoveryContext(
                    harness.session,
                    harness.binding,
                    harness.store.get_provider_state(harness.session.session_id),
                    "admission_fixture_recovery",
                )
            )
        )
        self.assertTrue(recovered.recovered)
        self.assertEqual(
            harness.store.get_provider_step_journal(record.journal_id).pairing_status,
            "ready",
        )
        return harness, adapter

    def test_queue_rejects_ready_pairing_before_new_turn_persistence(self) -> None:
        harness, _adapter = self._ready_pairing()

        with patch(
            "core.runtime.turn_queue_admission.remote_agentic_containment_reason",
            return_value=None,
        ), self.assertRaises(RuntimeTurnQueueRejectedError) as raised:
            queue_runtime_turn(
                harness.store,
                turn_id="turn-new-admission",
                session_id=harness.session.session_id,
                input_text="new input must not be claimed",
                now=NOW,
            )

        self.assertEqual(raised.exception.reason_code, "provider_pairing_ambiguous")
        self.assertFalse(
            any(
                turn.turn_id == "turn-new-admission"
                for turn in harness.store.list_turns(harness.session.session_id)
            )
        )

    def test_runtime_token_rejects_unresolved_persisted_pairing(self) -> None:
        harness, _adapter = self._ready_pairing()
        with patch.dict(
            "os.environ",
            {"MAVERICK_RUNTIME_API_SECRET": "terminal-gap-token-secret"},
            clear=True,
        ):
            token = issue_workspace_api_token(
                workspace_id=harness.session.workspace_id,
                runtime_session_id=harness.session.session_id,
                now=NOW,
            )
            self.assertIsNotNone(
                register_workspace_api_token(harness.store, token, now=NOW)
            )
            claims, reason = validate_workspace_api_token_lifecycle(
                harness.store,
                token,
                now=NOW,
            )

        self.assertIsNone(claims)
        self.assertEqual(reason, "provider_pairing_ambiguous")

    def test_prepare_and_continuation_admission_read_persisted_journal(self) -> None:
        harness, adapter = self._ready_pairing()
        prepared = asyncio.run(
            adapter.prepare(
                RuntimePrepareContext(
                    harness.session,
                    harness.binding,
                    harness.store.get_provider_state(harness.session.session_id),
                )
            )
        )
        self.assertFalse(prepared.ready)
        self.assertEqual(
            prepared.metadata["reason_code"],
            "provider_pairing_ambiguous",
        )

        with patch(
            "core.recovery.continuation_admission._validate_direct_authority"
        ):
            assessment = assess_runtime_session_admission(
                Mock(),
                harness.store,
                Mock(),
                session=harness.session,
                target_session_id="session-continuation-target",
                now=NOW,
            )
        self.assertEqual(assessment.status, "upgrade_required")
        self.assertEqual(assessment.detail_code, "provider_pairing_ambiguous")


if __name__ == "__main__":
    unittest.main()
