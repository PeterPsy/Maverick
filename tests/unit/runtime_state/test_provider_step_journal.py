from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
import unittest

from core.runtime.errors import RuntimeProviderStateError
from core.runtime.private_payload_models import PRIVATE_PAYLOAD_ENCRYPTION_PROFILE
from core.runtime.provider_state import ProviderPrivateEnvelope
from core.runtime.provider_step_journal import ProviderStepJournal
from core.runtime.session_collection import RuntimeSessionJsonCollection
from core.runtime.store import RuntimeCollections, RuntimeDocumentStore
from tests.support.collections import FakeCollection
from tests.support.hosted_agentic_harness import HostedAgenticHarness
from tests.support.repo import make_temp_repo_root


NOW = datetime(2026, 8, 27, tzinfo=UTC)
FAULT_POINTS = (
    "request_ready",
    "request_journaled",
    "provider_accepted",
    "provider_state_staged",
    "proposal_persisted",
    "provider_stream_completed",
    "disposition_persisted",
    "dispositions_completed",
    "result_persisted",
    "pairing_ready",
    "committed",
    "pairing_consumed",
)


class _InjectedCrash(RuntimeError):
    pass


class ProviderStepJournalTest(unittest.TestCase):
    def setUp(self) -> None:
        self.root = make_temp_repo_root(self)
        self.harness = HostedAgenticHarness(self)
        self.codec = SimpleNamespace(
            codec_id="fake-hosted-codec",
            codec_version="1",
            schema_version="1",
            content_type="application/vnd.maverick.fake-private",
        )
        self.envelope = ProviderPrivateEnvelope(
            schema_version="1",
            codec_id=self.codec.codec_id,
            codec_version=self.codec.codec_version,
            content_type=self.codec.content_type,
            opaque_state_ref="provider-private:v1:staged-fixture",
            content_sha256="a" * 64,
            size_bytes=16,
            encryption_profile=PRIVATE_PAYLOAD_ENCRYPTION_PROFILE,
            created_at=NOW,
            codec_identity="fake-hosted-codec:1:1",
            provider_request_id="request-journal",
            turn_generation="turn-hosted",
        )

    def test_fault_after_every_wal_transition_recovers_idempotently(self) -> None:
        for point in FAULT_POINTS:
            with self.subTest(point=point):
                store = self._document_store()

                def fault(observed, _record):
                    if observed == point:
                        raise _InjectedCrash(point)

                crashing = ProviderStepJournal(store=store, fault_hook=fault)
                with self.assertRaisesRegex(_InjectedCrash, point):
                    self._advance(crashing)

                restarted = ProviderStepJournal(store=store)
                terminal = self._advance(restarted)
                replayed = self._advance(restarted)

                self.assertEqual(terminal, replayed)
                self.assertEqual(terminal.commit_status, "committed")
                self.assertEqual(terminal.pairing_status, "consumed")
                self.assertEqual(terminal.observed_call_count, 1)
                self.assertEqual(terminal.revision, 11)

    def test_json_and_document_store_have_identical_cas_semantics(self) -> None:
        document = self._advance(ProviderStepJournal(store=self._document_store()))
        json_store = self._json_store()
        persisted = self._advance(ProviderStepJournal(store=json_store))
        restarted = self._json_store()
        reloaded = restarted.get_provider_step_journal(persisted.journal_id)

        self.assertEqual(document, persisted)
        self.assertEqual(reloaded, persisted)
        with self.assertRaisesRegex(
            RuntimeProviderStateError,
            "revision_conflict",
        ):
            restarted.update_provider_step_journal(
                reloaded,
                expected_revision=reloaded.revision - 1,
            )

    def test_request_ready_retry_ignores_wall_clock_but_preserves_created_at(self) -> None:
        store = self._document_store()
        journal = ProviderStepJournal(store=store)
        first = journal.begin_request(
            session=self.harness.session,
            binding=self.harness.binding,
            provider_state=self.harness.provider_state,
            request_id="request-journal",
            turn_id="turn-hosted",
            step_index=0,
            codec=self.codec,
            pairing_source_journal_id=None,
            now=NOW,
        )
        retried = journal.begin_request(
            session=self.harness.session,
            binding=self.harness.binding,
            provider_state=self.harness.provider_state,
            request_id="request-journal",
            turn_id="turn-hosted",
            step_index=0,
            codec=self.codec,
            pairing_source_journal_id=None,
            now=NOW.replace(second=1),
        )

        self.assertEqual(retried, first)
        self.assertEqual(retried.created_at, NOW)

    def test_failure_transitions_are_durable_and_restart_idempotent(self) -> None:
        cases = (
            ("pre_acceptance", "provider_response_invalid", False),
            ("proven_provider_terminal", "provider_output_incomplete", True),
        )
        for case, reason_code, accepted in cases:
            for fault_point in ("provider_stream_failed", "rolled_back"):
                with self.subTest(case=case, fault_point=fault_point):
                    store = self._document_store()

                    def fault(observed, _record):
                        if observed == fault_point:
                            raise _InjectedCrash(fault_point)

                    crashing = ProviderStepJournal(store=store, fault_hook=fault)
                    with self.assertRaisesRegex(_InjectedCrash, fault_point):
                        self._advance_failure(
                            crashing,
                            accepted=accepted,
                            reason_code=reason_code,
                        )
                    restarted = ProviderStepJournal(store=store)
                    terminal = self._advance_failure(
                        restarted,
                        accepted=accepted,
                        reason_code=reason_code,
                    )
                    replayed = self._advance_failure(
                        restarted,
                        accepted=accepted,
                        reason_code=reason_code,
                    )

                    self.assertEqual(replayed, terminal)
                    self.assertEqual(terminal.commit_status, "rolled_back")
                    self.assertEqual(
                        terminal.stream_failure_reason_code,
                        reason_code,
                    )

    def test_recovery_required_transition_is_durable_and_idempotent(self) -> None:
        store = self._document_store()

        def fault(observed, _record):
            if observed == "recovery_required":
                raise _InjectedCrash(observed)

        crashing = ProviderStepJournal(store=store, fault_hook=fault)
        record = self._failure_record(
            crashing,
            accepted=True,
            reason_code="provider_response_invalid",
        )
        with self.assertRaisesRegex(_InjectedCrash, "recovery_required"):
            crashing.require_recovery(
                record,
                reason_code="provider_acceptance_ambiguous",
                detail_private_ref="provider-recovery:v1:fixture",
                now=NOW,
            )

        restarted = ProviderStepJournal(store=store)
        persisted = store.get_provider_step_journal(record.journal_id)
        replayed = restarted.require_recovery(
            persisted,
            reason_code="provider_acceptance_ambiguous",
            detail_private_ref="provider-recovery:v1:fixture",
            now=NOW.replace(second=1),
        )
        self.assertEqual(replayed, persisted)
        self.assertEqual(replayed.commit_status, "recovery_required")

    def _advance_failure(
        self,
        journal: ProviderStepJournal,
        *,
        accepted: bool,
        reason_code: str,
    ):
        record = self._failure_record(
            journal,
            accepted=accepted,
            reason_code=reason_code,
        )
        if accepted:
            return journal.roll_back_proven_terminal_failure(record, now=NOW)
        return journal.roll_back(record, now=NOW)

    def _failure_record(
        self,
        journal: ProviderStepJournal,
        *,
        accepted: bool,
        reason_code: str,
    ):
        record = journal.begin_request(
            session=self.harness.session,
            binding=self.harness.binding,
            provider_state=self.harness.provider_state,
            request_id=f"request-failure:{accepted}:{reason_code}",
            turn_id="turn-hosted",
            step_index=0,
            codec=self.codec,
            pairing_source_journal_id=None,
            now=NOW,
        )
        record = journal.journal_request(record, now=NOW)
        if accepted:
            record = journal.accept(
                record,
                provider_response_id="response-failure",
                provider_upstream_id=None,
                now=NOW,
            )
        return journal.fail_stream(record, reason_code=reason_code, now=NOW)

    def _advance(self, journal: ProviderStepJournal):
        record = journal.begin_request(
            session=self.harness.session,
            binding=self.harness.binding,
            provider_state=self.harness.provider_state,
            request_id="request-journal",
            turn_id="turn-hosted",
            step_index=0,
            codec=self.codec,
            pairing_source_journal_id=None,
            now=NOW,
        )
        record = journal.journal_request(record, now=NOW)
        record = journal.accept(
            record,
            provider_response_id="response-journal",
            provider_upstream_id=None,
            now=NOW,
        )
        record = journal.stage_provider_state(record, self.envelope, now=NOW)
        record = journal.add_proposal(record, "proposal-journal", now=NOW)
        record = journal.complete_stream(
            record,
            final_output_validated=False,
            now=NOW,
        )
        record = journal.add_disposition(record, "disposition-journal", now=NOW)
        record = journal.complete_dispositions(record, now=NOW)
        record = journal.add_result(record, "result-journal", now=NOW)
        record = journal.mark_pairing_ready(record, now=NOW)
        record = journal.mark_committed(record, now=NOW)
        return journal.mark_pairing_consumed(record, now=NOW)

    @staticmethod
    def _document_store() -> RuntimeDocumentStore:
        return RuntimeDocumentStore(
            RuntimeCollections(
                sessions=FakeCollection(),
                turns=FakeCollection(),
                events=FakeCollection(),
                processes=FakeCollection(),
                states=FakeCollection(),
                threads=FakeCollection(),
                provider_step_journals=FakeCollection(),
            )
        )

    def _json_store(self) -> RuntimeDocumentStore:
        return RuntimeDocumentStore(
            RuntimeCollections(
                sessions=FakeCollection(),
                turns=FakeCollection(),
                events=FakeCollection(),
                processes=FakeCollection(),
                states=FakeCollection(),
                threads=FakeCollection(),
                provider_step_journals=RuntimeSessionJsonCollection(
                    start_path=self.root,
                    filename="provider_step_journal.json",
                ),
            )
        )


if __name__ == "__main__":
    unittest.main()
