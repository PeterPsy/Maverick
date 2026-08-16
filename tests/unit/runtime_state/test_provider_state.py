from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
import unittest

from core.runtime.errors import RuntimeProviderStateError
from core.runtime.provider_state import RuntimeProviderState
from core.runtime.store import RuntimeCollections, RuntimeDocumentStore
from tests.support.collections import FakeCollection


class RuntimeProviderStateTest(unittest.TestCase):
    def setUp(self) -> None:
        self.provider_states = FakeCollection()
        self.store = RuntimeDocumentStore(
            RuntimeCollections(
                sessions=FakeCollection(),
                turns=FakeCollection(),
                events=FakeCollection(),
                processes=FakeCollection(),
                states=FakeCollection(),
                threads=FakeCollection(),
                provider_states=self.provider_states,
            )
        )
        self.now = datetime(2026, 8, 16, tzinfo=UTC)
        self.initial = RuntimeProviderState(
            session_id="session-a",
            workspace_id="default",
            runtime_engine_id="codex",
            model_provider_id="codex",
            continuation_id=None,
            provider_thread_id=None,
            provider_request_id=None,
            provider_private_envelope=None,
            revision=0,
            turn_generation=None,
            updated_at=self.now,
        )

    def test_updates_advance_exact_revision_and_reject_stale_writer(self) -> None:
        self.store.initialize_provider_state(self.initial)
        revision_one = replace(
            self.initial,
            provider_thread_id="thread-a",
            continuation_id="thread-a",
            revision=1,
        )

        self.store.update_provider_state(revision_one, expected_revision=0)

        with self.assertRaises(RuntimeProviderStateError):
            self.store.update_provider_state(
                replace(revision_one, provider_thread_id="stale", revision=1),
                expected_revision=0,
            )
        self.assertEqual(self.store.get_provider_state("session-a"), revision_one)

    def test_identity_fields_cannot_change(self) -> None:
        self.store.initialize_provider_state(self.initial)

        with self.assertRaises(RuntimeProviderStateError):
            self.store.update_provider_state(
                replace(self.initial, runtime_engine_id="other", revision=1),
                expected_revision=0,
            )


if __name__ == "__main__":
    unittest.main()
