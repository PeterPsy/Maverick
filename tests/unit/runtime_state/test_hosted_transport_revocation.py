from __future__ import annotations

from types import SimpleNamespace
import unittest
from unittest.mock import patch

from core.runtime.execution import execute_runtime_turn
from core.runtime.hosted_agentic_models import HostedContentClassification
from tests.support.fake_agentic_provider import DeterministicFakeAgenticClient
from tests.support.hosted_agentic_harness import HostedAgenticHarness


class HostedTransportRevocationTest(unittest.TestCase):
    def test_revocation_during_endpoint_preflight_blocks_transport(self) -> None:
        harness = HostedAgenticHarness(self)
        live = True

        def revalidate(_context, classification):
            if live or classification.trust_level != "trusted_actor":
                return classification
            return HostedContentClassification(
                "unclassified",
                "untrusted_external",
                source_ref=classification.source_ref,
                source_revision=classification.source_revision,
                resource_identity=classification.resource_identity,
                classification_revision=None,
                content_digest=classification.content_digest,
                classification_authority_bound=None,
            )

        def preflight(_request, _credential):
            nonlocal live
            live = False
            return SimpleNamespace(snapshot_digest="d" * 64)

        harness.request_builder.classification_revalidator = revalidate
        harness.request_builder.semantic_compiler.classification_revalidator = (
            revalidate
        )
        client = DeterministicFakeAgenticClient()
        events = []

        result = execute_runtime_turn(
            session=harness.session,
            provider=harness.provider,
            input_text="Use only synthetic fixture data.",
            agentic_adapter=harness.adapter(
                client,
                request_preflight=preflight,
            ),
            provider_state=harness.store.get_provider_state("session-hosted"),
            correlation_id="turn-hosted",
            effective_authority=harness.authority,
            event_sink=events.append,
        )

        self.assertEqual(result.exit_code, 1)
        self.assertEqual(client.requests, [])
        self.assertEqual(
            [event.payload for event in events if event.event_type == "runtime.error"],
            [{"reason_code": "egress_data_class_denied"}],
        )

    def test_revocation_after_request_journal_blocks_lazy_transport(self) -> None:
        harness = HostedAgenticHarness(self)
        live = True

        def revalidate(_context, classification):
            if live or classification.trust_level != "trusted_actor":
                return classification
            return HostedContentClassification(
                "unclassified",
                "untrusted_external",
                source_ref=classification.source_ref,
                source_revision=classification.source_revision,
                resource_identity=classification.resource_identity,
                classification_revision=None,
                content_digest=classification.content_digest,
                classification_authority_bound=None,
            )

        harness.request_builder.classification_revalidator = revalidate
        harness.request_builder.semantic_compiler.classification_revalidator = (
            revalidate
        )
        client = DeterministicFakeAgenticClient()
        adapter = harness.adapter(
            client,
            request_preflight=lambda _request, _credential: SimpleNamespace(
                snapshot_digest="e" * 64
            ),
        )
        journal_request = adapter.loop.provider_step_journal.journal_request

        def revoke_after_journal(record):
            nonlocal live
            saved = journal_request(record)
            live = False
            return saved

        events = []
        with patch.object(
            adapter.loop.provider_step_journal,
            "journal_request",
            side_effect=revoke_after_journal,
        ):
            result = execute_runtime_turn(
                session=harness.session,
                provider=harness.provider,
                input_text="Use only synthetic fixture data.",
                agentic_adapter=adapter,
                provider_state=harness.store.get_provider_state(
                    "session-hosted"
                ),
                correlation_id="turn-hosted",
                effective_authority=harness.authority,
                event_sink=events.append,
            )

        self.assertEqual(result.exit_code, 1)
        self.assertEqual(client.requests, [])
        self.assertEqual(
            [event.payload for event in events if event.event_type == "runtime.error"],
            [{"reason_code": "egress_data_class_denied"}],
        )


if __name__ == "__main__":
    unittest.main()
