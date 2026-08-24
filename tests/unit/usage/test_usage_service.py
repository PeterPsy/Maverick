"""Usage ingestion, chat aggregation, and time-series tests."""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
import unittest

from core.shared.in_memory_collection import InMemoryCollection
from core.runtime.execution_events import RuntimeExecutionEvent
from core.runtime.turn_submission_service_output_text import _RuntimeTurnOutputRecorder
from core.usage.service import ingest_runtime_usage
from core.usage.store import UsageCollections, UsageDocumentStore
from core.usage.timeseries import usage_timeseries_payload


class _RuntimeStore:
    def __init__(self, *sessions) -> None:
        self.sessions = {session.session_id: session for session in sessions}
        self.events = []

    def get_session(self, session_id: str):
        return self.sessions[session_id]

    def save_event(self, event):
        self.events.append(event)
        return event


class _EventBus:
    def __init__(self) -> None:
        self.events = []

    def publish(self, event) -> None:
        self.events.append(event)


def _session(
    session_id: str,
    *,
    creator_runtime_session_id: str | None = None,
    predecessor_session_id: str | None = None,
):
    return SimpleNamespace(
        session_id=session_id,
        workspace_id="workspace-1",
        creator_runtime_session_id=creator_runtime_session_id,
        predecessor_session_id=predecessor_session_id,
        continuation_successor_session_id=None,
        execution_binding=SimpleNamespace(model_provider_id="codex", model_id="gpt-test"),
        hosted_provider_id=None,
        hosted_model_id=None,
        provider_id="codex",
    )


class UsageServiceTest(unittest.TestCase):
    def setUp(self) -> None:
        self.root = _session("root-session")
        self.child = _session("child-session", creator_runtime_session_id=self.root.session_id)
        self.store = UsageDocumentStore(
            UsageCollections(
                samples=InMemoryCollection(),
                buckets=InMemoryCollection(),
                quota_snapshots=InMemoryCollection(),
            )
        )
        self.state = SimpleNamespace(
            usage_store=self.store,
            runtime_store=_RuntimeStore(self.root, self.child),
            runtime_event_bus=_EventBus(),
            provider_registry=None,
        )

    def test_output_recorder_replaces_raw_usage_with_root_chat_projection(self) -> None:
        recorder = _RuntimeTurnOutputRecorder(
            self.state,
            session_id=self.child.session_id,
            turn_id="child-turn",
        )

        recorded = recorder.record(
            RuntimeExecutionEvent(
                event_type="provider.usage",
                payload={
                    "usage_id": "child-request-1",
                    "provider_id": "openrouter",
                    "model_id": "fast-model",
                    "semantics": "incremental",
                    "input_tokens": 20,
                    "output_tokens": 5,
                    "total_tokens": 25,
                },
            )
        )

        self.assertIsNotNone(recorded)
        assert recorded is not None
        self.assertEqual(recorded.event_type, "runtime.usage.updated")
        self.assertEqual(recorded.session_id, self.root.session_id)
        self.assertIsNone(recorded.turn_id)
        self.assertEqual(recorded.payload["tokens"]["total_tokens"], 25)
        self.assertEqual([event.event_type for event in self.state.runtime_store.events], ["runtime.usage.updated"])
        self.assertEqual(self.state.runtime_event_bus.events, [recorded])

    def test_cumulative_reports_track_context_without_double_counting_chat_tokens(self) -> None:
        first = ingest_runtime_usage(
            self.state,
            session_id=self.root.session_id,
            turn_id="turn-1",
            observed_at=datetime(2026, 8, 20, 10, 5, tzinfo=UTC),
            payload={
                "usage_id": "codex-snapshot-1",
                "provider_id": "codex",
                "model_id": "gpt-test",
                "source": "codex_app_server",
                "semantics": "cumulative",
                "token_accuracy": "exact",
                "context_accuracy": "exact",
                "input_tokens": 100,
                "cached_input_tokens": 20,
                "output_tokens": 40,
                "reasoning_output_tokens": 10,
                "total_tokens": 140,
                "context_tokens": 120,
                "context_window_tokens": 200,
            },
        )
        second = ingest_runtime_usage(
            self.state,
            session_id=self.root.session_id,
            turn_id="turn-2",
            observed_at=datetime(2026, 8, 20, 11, 5, tzinfo=UTC),
            payload={
                "usage_id": "codex-snapshot-2",
                "provider_id": "codex",
                "model_id": "gpt-test",
                "source": "codex_app_server",
                "semantics": "cumulative",
                "token_accuracy": "exact",
                "context_accuracy": "exact",
                "input_tokens": 180,
                "cached_input_tokens": 30,
                "output_tokens": 70,
                "reasoning_output_tokens": 15,
                "total_tokens": 250,
                "context_tokens": 90,
                "context_window_tokens": 200,
            },
        )

        self.assertIsNotNone(first)
        self.assertIsNotNone(second)
        assert second is not None
        self.assertEqual(second.summary.tokens.total_tokens, 250)
        self.assertEqual(second.summary.tokens.input_tokens, 150)
        self.assertEqual(second.summary.tokens.cached_input_tokens, 30)
        self.assertEqual(second.summary.tokens.output_tokens, 55)
        self.assertEqual(second.summary.tokens.reasoning_output_tokens, 15)
        self.assertEqual(second.summary.context_tokens, 90)
        self.assertEqual(second.summary.context_window_tokens, 200)
        self.assertEqual(second.summary.context_used_percent, 45.0)
        self.assertEqual(second.summary.token_accuracy, "exact")

    def test_first_codex_snapshot_uses_latest_request_instead_of_historical_total(self) -> None:
        first = ingest_runtime_usage(
            self.state,
            session_id=self.root.session_id,
            turn_id="turn-1",
            observed_at=datetime(2026, 8, 20, 10, 5, tzinfo=UTC),
            payload={
                "usage_id": "codex-historical-snapshot-1",
                "provider_id": "codex",
                "model_id": "gpt-test",
                "source": "codex_app_server",
                "semantics": "cumulative",
                "input_tokens": 52_027_036,
                "cached_input_tokens": 51_097_088,
                "output_tokens": 119_710,
                "reasoning_output_tokens": 40_856,
                "total_tokens": 52_146_746,
                "latest_input_tokens": 238_000,
                "latest_cached_input_tokens": 225_000,
                "latest_output_tokens": 2_516,
                "latest_reasoning_output_tokens": 1_000,
                "latest_total_tokens": 240_516,
                "context_tokens": 240_516,
                "context_window_tokens": 258_400,
            },
        )
        second = ingest_runtime_usage(
            self.state,
            session_id=self.root.session_id,
            turn_id="turn-1",
            observed_at=datetime(2026, 8, 20, 10, 6, tzinfo=UTC),
            payload={
                "usage_id": "codex-historical-snapshot-2",
                "provider_id": "codex",
                "model_id": "gpt-test",
                "source": "codex_app_server",
                "semantics": "cumulative",
                "input_tokens": 52_267_000,
                "cached_input_tokens": 51_244_288,
                "output_tokens": 120_637,
                "reasoning_output_tokens": 41_100,
                "total_tokens": 52_387_637,
                "latest_input_tokens": 239_900,
                "latest_cached_input_tokens": 147_200,
                "latest_output_tokens": 991,
                "latest_reasoning_output_tokens": 250,
                "latest_total_tokens": 240_891,
                "context_tokens": 240_891,
                "context_window_tokens": 258_400,
            },
        )

        self.assertIsNotNone(first)
        self.assertIsNotNone(second)
        assert first is not None and second is not None
        self.assertEqual(first.summary.tokens.total_tokens, 240_516)
        self.assertEqual(first.sample.reported_total_tokens, 52_146_746)
        self.assertEqual(first.sample.total_tokens, 240_516)
        self.assertEqual(second.summary.tokens.total_tokens, 481_407)

    def test_legacy_codex_full_snapshot_is_baseline_for_later_deltas(self) -> None:
        first = ingest_runtime_usage(
            self.state,
            session_id=self.root.session_id,
            turn_id="turn-legacy",
            observed_at=datetime(2026, 8, 20, 10, 5, tzinfo=UTC),
            payload={
                "usage_id": "legacy-codex-snapshot",
                "provider_id": "codex",
                "model_id": "gpt-test",
                "source": "codex_app_server",
                "semantics": "cumulative",
                "input_tokens": 52_027_036,
                "cached_input_tokens": 51_097_088,
                "output_tokens": 119_710,
                "reasoning_output_tokens": 40_856,
                "total_tokens": 52_146_746,
                "context_tokens": 240_516,
                "context_window_tokens": 258_400,
            },
        )

        second = ingest_runtime_usage(
            self.state,
            session_id=self.root.session_id,
            turn_id="turn-legacy",
            observed_at=datetime(2026, 8, 20, 10, 6, tzinfo=UTC),
            payload={
                "usage_id": "legacy-codex-snapshot-next",
                "provider_id": "codex",
                "model_id": "gpt-test",
                "source": "codex_app_server",
                "semantics": "cumulative",
                "input_tokens": 52_267_000,
                "cached_input_tokens": 51_244_288,
                "output_tokens": 120_637,
                "reasoning_output_tokens": 41_100,
                "total_tokens": 52_387_637,
                "context_tokens": 240_891,
                "context_window_tokens": 258_400,
            },
        )

        self.assertIsNotNone(first)
        self.assertIsNotNone(second)
        assert first is not None and second is not None
        self.assertEqual(first.summary.tokens.total_tokens, 0)
        self.assertEqual(second.summary.tokens.total_tokens, 240_891)
        canonical = self.store.list_samples(session_id=self.root.session_id)
        self.assertEqual(canonical[0].total_tokens, 0)
        self.assertEqual(canonical[0].reported_total_tokens, 52_146_746)
        self.assertEqual(canonical[1].total_tokens, 240_891)

    def test_delegated_usage_rolls_up_to_root_and_duplicate_reports_are_idempotent(self) -> None:
        payload = {
            "usage_id": "child-request-1",
            "provider_id": "openrouter",
            "model_id": "fast-model",
            "source": "hosted_text_generation",
            "semantics": "incremental",
            "input_tokens": 20,
            "output_tokens": 5,
            "total_tokens": 25,
        }

        first = ingest_runtime_usage(
            self.state,
            session_id=self.child.session_id,
            turn_id="child-turn",
            observed_at=datetime(2026, 8, 20, 12, 10, tzinfo=UTC),
            payload=payload,
        )
        duplicate = ingest_runtime_usage(
            self.state,
            session_id=self.child.session_id,
            turn_id="child-turn",
            observed_at=datetime(2026, 8, 20, 12, 11, tzinfo=UTC),
            payload=payload,
        )

        self.assertIsNotNone(first)
        self.assertIsNotNone(duplicate)
        assert first is not None and duplicate is not None
        self.assertTrue(first.inserted)
        self.assertFalse(duplicate.inserted)
        self.assertEqual(duplicate.summary.root_session_id, self.root.session_id)
        self.assertEqual(duplicate.summary.tokens.total_tokens, 25)
        self.assertEqual(duplicate.summary.direct_tokens.total_tokens, 0)
        self.assertEqual(duplicate.summary.delegated_tokens.total_tokens, 25)
        self.assertEqual(duplicate.summary.sample_count, 1)

    def test_continuation_usage_remains_direct_and_notifies_the_current_session(self) -> None:
        continuation = _session(
            "root-continuation",
            predecessor_session_id=self.root.session_id,
        )
        self.root.continuation_successor_session_id = continuation.session_id
        self.state.runtime_store.sessions[continuation.session_id] = continuation

        ingest_runtime_usage(
            self.state,
            session_id=self.root.session_id,
            turn_id="root-turn",
            observed_at=datetime(2026, 8, 20, 12, 0, tzinfo=UTC),
            payload={
                "usage_id": "root-usage",
                "semantics": "incremental",
                "input_tokens": 10,
                "total_tokens": 10,
                "context_tokens": 10,
                "context_window_tokens": 100,
            },
        )
        continued = ingest_runtime_usage(
            self.state,
            session_id=continuation.session_id,
            turn_id="continuation-turn",
            observed_at=datetime(2026, 8, 20, 12, 5, tzinfo=UTC),
            payload={
                "usage_id": "continuation-usage",
                "semantics": "incremental",
                "input_tokens": 15,
                "total_tokens": 15,
                "context_tokens": 60,
                "context_window_tokens": 100,
            },
        )

        self.assertIsNotNone(continued)
        assert continued is not None
        self.assertEqual(continued.notification_session_id, continuation.session_id)
        self.assertEqual(continued.summary.root_session_id, self.root.session_id)
        self.assertEqual(continued.summary.direct_tokens.total_tokens, 25)
        self.assertEqual(continued.summary.delegated_tokens.total_tokens, 0)
        self.assertEqual(continued.summary.context_tokens, 60)

    def test_hourly_series_is_gap_filled_and_filterable(self) -> None:
        for usage_id, hour, provider_id, tokens in (
            ("sample-1", 10, "codex", 40),
            ("sample-2", 12, "openrouter", 25),
        ):
            ingest_runtime_usage(
                self.state,
                session_id=self.root.session_id,
                turn_id=usage_id,
                observed_at=datetime(2026, 8, 20, hour, 5, tzinfo=UTC),
                payload={
                    "usage_id": usage_id,
                    "provider_id": provider_id,
                    "model_id": "gpt-test",
                    "semantics": "incremental",
                    "input_tokens": tokens,
                    "total_tokens": tokens,
                },
            )

        payload = usage_timeseries_payload(
            self.store,
            workspace_id="workspace-1",
            resolution="hour",
            periods=3,
            now=datetime(2026, 8, 20, 12, 30, tzinfo=UTC),
        )
        codex_payload = usage_timeseries_payload(
            self.store,
            workspace_id="workspace-1",
            resolution="hour",
            periods=3,
            provider_id="codex",
            now=datetime(2026, 8, 20, 12, 30, tzinfo=UTC),
        )

        self.assertEqual([item["total_tokens"] for item in payload["items"]], [40, 0, 25])
        self.assertEqual(payload["totals"]["total_tokens"], 65)
        self.assertEqual(
            payload["facets"],
            {
                "providers": [
                    {"provider_id": "codex", "model_ids": ["gpt-test"]},
                    {"provider_id": "openrouter", "model_ids": ["gpt-test"]},
                ]
            },
        )
        self.assertEqual([item["total_tokens"] for item in codex_payload["items"]], [40, 0, 0])
        self.assertEqual(codex_payload["facets"], payload["facets"])


if __name__ == "__main__":
    unittest.main()
